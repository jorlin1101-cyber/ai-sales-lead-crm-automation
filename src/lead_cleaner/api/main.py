import logging
import hashlib
import hmac
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Annotated, cast

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import ValidationError
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, Response

from lead_cleaner.api.error_handlers import register_error_handlers
from lead_cleaner.api.request_context import (
    REQUEST_ID_HEADER,
    get_request_id,
    reset_request_id,
    resolve_request_id,
    set_request_id,
)
from lead_cleaner.config import Settings
from lead_cleaner.api.access import install_access
from lead_cleaner.observability import log_event
from lead_cleaner.rag.retriever import (
    CloseableRagRetriever,
    RagRetriever,
)
from lead_cleaner.rag.retriever_factory import create_rag_retriever
from lead_cleaner.schemas.crm import NotionCrmStatus, NotionSyncRequest, NotionSyncResponse
from lead_cleaner.schemas.conversation import (
    ConversationMessageRequest,
    ConversationSummary,
    ConversationTimelineItem,
    ConversationTurnResult,
    DraftReviewRequest,
    DraftSyncRequest,
)
from lead_cleaner.schemas.lead import LeadProcessingResult, RawLeadInput
from lead_cleaner.services.feature_extractor import (
    CloseableFeatureExtractor,
    FeatureExtractor,
)
from lead_cleaner.services.feature_extractor_factory import create_feature_extractor
from lead_cleaner.services.notion_crm import (
    NotionCrmNotConfiguredError,
    NotionCrmWriter,
    create_notion_crm_writer,
)
from lead_cleaner.services.conversation_service import ConversationService
from lead_cleaner.services.conversation_llm import QwenConversationLLM
from lead_cleaner.services.conversation_store import (
    ConversationIdempotencyConflictError,
    ConversationMessageProcessingError,
    ConversationStore,
)
from lead_cleaner.services.processor import process_lead
from lead_cleaner.services.crm_workflow import sync_reviewed
from lead_cleaner.services.quotation import QuoteInput, estimate_quote
from lead_cleaner.services.rule_feature_extractor import RuleFeatureExtractor
from lead_cleaner.rag.retriever import DisabledRagRetriever
from sqlalchemy import text
from lead_cleaner.services.recommendation_generator import (
    CloseableRecommendationGenerator,
    RecommendationGenerator,
)
from lead_cleaner.services.recommendation_generator_factory import (
    create_recommendation_generator,
)

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def create_app(*, settings: Settings | None = None) -> FastAPI:
    """Build the API and own one feature extractor for its full lifetime."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_settings = settings or Settings()
        feature_extractor = create_feature_extractor(resolved_settings)
        rag_retriever: RagRetriever | None = None
        recommendation_generator: RecommendationGenerator | None = None
        notion_crm_writer: NotionCrmWriter | None = None
        conversation_store: ConversationStore | None = None
        conversation_llm: QwenConversationLLM | None = None

        try:
            rag_retriever = create_rag_retriever(resolved_settings)
            conversation_llm = QwenConversationLLM.from_settings(resolved_settings)
            recommendation_generator = create_recommendation_generator(resolved_settings)
            notion_crm_writer = create_notion_crm_writer(resolved_settings)
            conversation_store = ConversationStore(
                resolved_settings.conversation_database_url
                or resolved_settings.conversation_db_path,
                create_schema=resolved_settings.conversation_auto_create_schema,
            )

            app.state.settings = resolved_settings
            app.state.feature_extractor = feature_extractor
            app.state.rag_retriever = rag_retriever
            app.state.recommendation_generator = recommendation_generator
            app.state.notion_crm_writer = notion_crm_writer
            app.state.conversation_service = ConversationService(conversation_store)
            app.state.conversation_llm = conversation_llm

            yield
        finally:
            if conversation_llm is not None:
                conversation_llm.close()
            if conversation_store is not None:
                conversation_store.close()
            if notion_crm_writer is not None:
                notion_crm_writer.close()

            if isinstance(
                recommendation_generator,
                CloseableRecommendationGenerator,
            ):
                recommendation_generator.close()

            if isinstance(rag_retriever, CloseableRagRetriever):
                rag_retriever.close()

            if isinstance(feature_extractor, CloseableFeatureExtractor):
                feature_extractor.close()

    api = FastAPI(
        title="AI Sales Lead Cleaner API",
        version="0.3.0",
        lifespan=lifespan,
    )
    register_error_handlers(api)
    install_access(api)
    api.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")

    @api.middleware("http")
    async def add_request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started = perf_counter()
        log_event(
            "request_started",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
        except Exception as error:
            log_event(
                "request_failed",
                level=logging.ERROR,
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                error_type=type(error).__name__,
            )
            raise
        else:
            response.headers[REQUEST_ID_HEADER] = request_id
            log_event(
                "request_completed",
                level=(logging.INFO if response.status_code < 400 else logging.WARNING),
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((perf_counter() - started) * 1000, 3),
            )
            return response
        finally:
            reset_request_id(token)

    def get_feature_extractor(request: Request) -> FeatureExtractor:
        if request.state.role == "guest":
            return RuleFeatureExtractor()
        return cast(FeatureExtractor, request.app.state.feature_extractor)

    def get_rag_retriever(request: Request) -> RagRetriever:
        if (
            request.state.role == "guest"
            and request.app.state.settings.rag_backend != "keyword_rrf"
        ):
            return DisabledRagRetriever()
        return cast(RagRetriever, request.app.state.rag_retriever)

    def get_recommendation_generator(
        request: Request,
    ) -> RecommendationGenerator | None:
        if request.state.role == "guest":
            return None
        return cast(
            RecommendationGenerator | None,
            request.app.state.recommendation_generator,
        )

    def get_notion_crm_writer(request: Request) -> NotionCrmWriter | None:
        if request.state.role == "guest":
            return None
        return cast(NotionCrmWriter | None, request.app.state.notion_crm_writer)

    def get_conversation_service(request: Request) -> ConversationService:
        return cast(ConversationService, request.app.state.conversation_service)

    def require_owner(request: Request, conversation_id: str) -> ConversationStore:
        store = request.app.state.conversation_service.store
        if store.get_summary(conversation_id) is None:
            raise HTTPException(404, "Conversation not found")
        if request.state.role != "operator":
            owner = store.get_event(f"owner_{conversation_id}")
            if not owner or owner["payload"]["owner"] != request.state.principal:
                raise HTTPException(404, "Conversation not found")
        return store

    @api.get("/session")
    def session_info(request: Request) -> dict:
        return {"role": request.state.role, "mode": request.app.state.settings.service_access_mode}

    @api.post("/webhooks/inbound", response_model=ConversationTurnResult)
    async def inbound_webhook(request: Request):
        secret = request.app.state.settings.inbound_webhook_secret
        if secret is None:
            raise HTTPException(404, "Inbound channel not configured")
        stamp = request.headers.get("x-leadflow-timestamp", "")
        if not stamp.isdigit() or abs(time.time() - int(stamp)) > 300:
            raise HTTPException(401, "Invalid webhook timestamp")
        body = await request.body()
        if len(body) > 65536:
            raise HTTPException(413, "Webhook body too large")
        signature = hmac.new(
            secret.get_secret_value().encode(), stamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, request.headers.get("x-leadflow-signature", "")):
            raise HTTPException(401, "Invalid webhook signature")
        try:
            payload = ConversationMessageRequest.model_validate_json(body)
        except ValidationError as error:
            raise HTTPException(422, "Invalid inbound message payload") from error
        # Run blocking model/DB work off the event loop.
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(
            process_conversation_message,
            payload,
            request,
            request.app.state.conversation_service,
            get_feature_extractor(request),
            get_rag_retriever(request),
            get_recommendation_generator(request),
        )

    @api.get("/ready")
    def readiness(request: Request) -> dict:
        try:
            with request.app.state.conversation_service.store.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as error:
            raise HTTPException(503, "Database is not ready") from error
        model = request.app.state.conversation_llm if request.state.role != "guest" else None
        return {
            "database": "ready",
            "rag_backend": request.app.state.settings.rag_backend,
            "conversation_llm": {
                "configured": model is not None,
                "model": model.model if model else None,
                "note": "Configured does not imply a successful call; see each turn's llm_trace.",
            },
        }

    @api.get("/conversations")
    def conversation_list(request: Request) -> list:
        return request.app.state.conversation_service.store.list_conversations(
            request.state.principal
        )

    @api.get("/conversations/{conversation_id}/latest")
    def latest_conversation(conversation_id: str, request: Request):
        result = require_owner(request, conversation_id).latest_result(conversation_id)
        if result is None:
            raise HTTPException(404, "No completed turn")
        return result

    @api.post("/conversations/{conversation_id}/drafts/{draft_id}/review")
    def review_conversation_draft(
        conversation_id: str, draft_id: str, payload: DraftReviewRequest, request: Request
    ):
        store = require_owner(request, conversation_id)
        if request.state.role != "operator" and payload.action == "record_sent":
            raise HTTPException(403, "Visitors cannot record external sending")
        try:
            return store.review_draft(conversation_id, draft_id, payload, request.state.principal)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except (ConversationIdempotencyConflictError, ConversationMessageProcessingError) as error:
            raise HTTPException(409, str(error)) from error

    @api.post("/conversations/{conversation_id}/quote")
    def quote_conversation(conversation_id: str, payload: QuoteInput, request: Request):
        store = require_owner(request, conversation_id)
        if request.state.role != "operator":
            raise HTTPException(403, "Visitors cannot access internal prices")
        try:
            with store.processing_lease(conversation_id):
                facts = store.get_facts(conversation_id)
                if any(f.status == "conflicted" for f in facts):
                    raise ValueError("Resolve conflicting customer facts before quoting.")
                group = next((f.value for f in facts if f.key == "group_size"), None)
                if group and group != str(payload.group_size):
                    raise ValueError("Group size differs from the current customer facts.")
                quote = estimate_quote(payload, request.app.state.settings.pricing_rules_path)
                quote["facts"] = [f.model_dump() for f in facts]
                quote["quote_id"] = store.put_event("quote", conversation_id, dict(quote))
                return quote
        except (ValueError, ConversationMessageProcessingError) as error:
            raise HTTPException(409, str(error)) from error

    @api.post("/crm/notion/conversations/{conversation_id}", response_model=NotionSyncResponse)
    def sync_conversation_crm(
        conversation_id: str,
        payload: DraftSyncRequest,
        request: Request,
        writer: Annotated[NotionCrmWriter | None, Depends(get_notion_crm_writer)],
    ):
        store = require_owner(request, conversation_id)
        if request.state.role != "operator":
            raise HTTPException(403, "Visitors cannot write to CRM")
        if writer is None:
            raise NotionCrmNotConfiguredError("Notion CRM is disabled.")
        try:
            with store.processing_lease(conversation_id):
                current = store.latest_result(conversation_id)
                if current is None:
                    raise HTTPException(404, "Conversation not found")
                draft = current.reply_draft
                summary = store.get_summary(conversation_id)
                if (
                    draft.draft_id != payload.draft_id
                    or draft.draft_version != payload.expected_version
                    or draft.status not in {"approved", "sent"}
                    or current.state == "do_not_contact"
                    or summary is None
                    or summary.turn_number != draft.turn_number
                ):
                    raise HTTPException(409, "Review the latest draft version before CRM sync.")
                return sync_reviewed(
                    store,
                    writer,
                    result=current.current_analysis,
                    draft=draft.body_text,
                    operator=request.state.principal,
                    version=f"{draft.draft_id}:v{draft.draft_version}",
                )
        except ConversationMessageProcessingError as error:
            raise HTTPException(409, str(error)) from error

    @api.get("/", include_in_schema=False)
    def frontend() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html")

    @api.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @api.post("/process-lead", response_model=LeadProcessingResult)
    def process_lead_api(
        raw_lead: RawLeadInput,
        request: Request,
        feature_extractor: Annotated[
            FeatureExtractor,
            Depends(get_feature_extractor),
        ],
        rag_retriever: Annotated[
            RagRetriever,
            Depends(get_rag_retriever),
        ],
        recommendation_generator: Annotated[
            RecommendationGenerator | None,
            Depends(get_recommendation_generator),
        ],
    ) -> LeadProcessingResult:
        result = process_lead(
            raw_lead,
            feature_extractor=feature_extractor,
            rag_retriever=rag_retriever,
            recommendation_generator=recommendation_generator,
        )
        analysis = result.analysis_result
        log_event(
            "lead_processing_completed",
            request_id=get_request_id(),
            validation_status=("valid" if result.validation_result.is_valid else "invalid"),
            source_count=len(result.sources),
            execution_mode=(analysis.metadata.execution_mode if analysis else None),
            analysis_method=(analysis.metadata.analysis_method if analysis else None),
            fallback_reason=(analysis.metadata.fallback_reason if analysis else None),
            intent_level=(analysis.decision.intent_level if analysis else None),
            disposition=(analysis.decision.disposition if analysis else None),
            policy_version=(analysis.decision.policy_version if analysis else None),
            retrieval_method=(analysis.metadata.retrieval_method if analysis else None),
            recommendation_method=(analysis.metadata.recommendation_method if analysis else None),
        )
        if analysis and analysis.metadata.fallback_reason:
            log_event(
                "feature_fallback_used",
                level=logging.WARNING,
                request_id=get_request_id(),
                execution_mode=analysis.metadata.execution_mode,
                analysis_method=analysis.metadata.analysis_method,
                fallback_reason=analysis.metadata.fallback_reason,
            )
        if analysis and analysis.metadata.retrieval_method == "unavailable":
            log_event(
                "rag_degraded",
                level=logging.WARNING,
                request_id=get_request_id(),
                retrieval_method=analysis.metadata.retrieval_method,
                recommendation_method=analysis.metadata.recommendation_method,
            )
        store = request.app.state.conversation_service.store
        snapshot = store.put_event(
            "lead_analysis",
            request.state.principal,
            {"raw": raw_lead.model_dump(mode="json"), "result": result.model_dump(mode="json")},
        )
        return result.model_copy(update={"analysis_id": snapshot})

    @api.post("/conversations/messages", response_model=ConversationTurnResult)
    def process_conversation_message(
        message_request: ConversationMessageRequest,
        request: Request,
        conversation_service: Annotated[
            ConversationService,
            Depends(get_conversation_service),
        ],
        feature_extractor: Annotated[
            FeatureExtractor,
            Depends(get_feature_extractor),
        ],
        rag_retriever: Annotated[
            RagRetriever,
            Depends(get_rag_retriever),
        ],
        recommendation_generator: Annotated[
            RecommendationGenerator | None,
            Depends(get_recommendation_generator),
        ],
    ) -> ConversationTurnResult:
        try:
            if request.state.role == "guest":
                message_request = message_request.model_copy(
                    update={
                        "account_id": hashlib.sha256(
                            f"{request.state.principal}:{message_request.account_id}".encode()
                        ).hexdigest()
                    }
                )
            result = conversation_service.process_message(
                message_request,
                feature_extractor=feature_extractor,
                rag_retriever=rag_retriever,
                recommendation_generator=recommendation_generator,
                conversation_llm=(
                    request.app.state.conversation_llm if request.state.role != "guest" else None
                ),
            )
            conversation_service.store.bind_owner(result.conversation_id, request.state.principal)
        except ConversationIdempotencyConflictError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "idempotency_key_reused",
                    "message": str(error),
                },
            ) from error
        except ConversationMessageProcessingError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "message_processing_conflict",
                    "message": str(error),
                },
            ) from error
        log_event(
            "conversation_turn_processed",
            request_id=get_request_id(),
            conversation_id=result.conversation_id,
            turn_number=result.turn_number,
            channel=message_request.channel,
            idempotency_status=result.idempotency_status,
            requires_human_review=result.requires_human_review,
        )
        return result

    @api.get(
        "/conversations/{conversation_id}",
        response_model=ConversationSummary,
    )
    def get_conversation(
        conversation_id: str,
        request: Request,
        conversation_service: Annotated[
            ConversationService,
            Depends(get_conversation_service),
        ],
    ) -> ConversationSummary:
        summary = require_owner(request, conversation_id).get_summary(conversation_id)
        if summary is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return summary

    @api.get(
        "/conversations/{conversation_id}/timeline",
        response_model=list[ConversationTimelineItem],
    )
    def get_conversation_timeline(
        conversation_id: str,
        request: Request,
        conversation_service: Annotated[
            ConversationService,
            Depends(get_conversation_service),
        ],
    ) -> list[ConversationTimelineItem]:
        require_owner(request, conversation_id)
        if conversation_service.store.get_summary(conversation_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conversation_service.store.timeline(conversation_id)

    @api.get("/crm/notion/status", response_model=NotionCrmStatus)
    def notion_crm_status(
        writer: Annotated[NotionCrmWriter | None, Depends(get_notion_crm_writer)],
    ) -> NotionCrmStatus:
        if writer is None:
            return NotionCrmStatus(
                configured=False,
                connected=False,
                message="Notion CRM 尚未配置，分析功能仍可正常演示。",
            )
        return writer.status()

    @api.post("/crm/notion/leads", response_model=NotionSyncResponse)
    def sync_lead_to_notion(
        sync_request: NotionSyncRequest,
        request: Request,
        writer: Annotated[NotionCrmWriter | None, Depends(get_notion_crm_writer)],
        feature_extractor: Annotated[
            FeatureExtractor,
            Depends(get_feature_extractor),
        ],
        rag_retriever: Annotated[
            RagRetriever,
            Depends(get_rag_retriever),
        ],
        recommendation_generator: Annotated[
            RecommendationGenerator | None,
            Depends(get_recommendation_generator),
        ],
    ) -> NotionSyncResponse:
        if writer is None:
            raise NotionCrmNotConfiguredError("Notion CRM is disabled.")
        store = request.app.state.conversation_service.store
        event = store.get_event(sync_request.analysis_id or "")
        if (
            not event
            or event["kind"] != "lead_analysis"
            or event["conversation_id"] != request.state.principal
        ):
            raise HTTPException(409, "Analyze and review a saved version before CRM sync.")
        if event["payload"]["raw"] != sync_request.raw_lead.model_dump(mode="json"):
            raise HTTPException(409, "The input changed; analyze it again before approving.")
        trusted_result = LeadProcessingResult.model_validate(event["payload"]["result"])
        version = hashlib.sha256(
            f"{sync_request.analysis_id}:{sync_request.approved_followup_email}".encode()
        ).hexdigest()
        try:
            response = sync_reviewed(
                store,
                writer,
                result=trusted_result,
                draft=sync_request.approved_followup_email,
                operator=request.state.principal,
                version=version,
            )
        except ConversationMessageProcessingError as error:
            raise HTTPException(409, str(error)) from error
        log_event(
            "notion_crm_sync_completed",
            request_id=get_request_id(),
            lead_id=response.lead_id,
            page_id=response.page_id,
            operator_name=request.state.principal,
        )
        return response

    return api


app = create_app()
