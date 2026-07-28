import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Annotated, cast

from fastapi import Depends, FastAPI, Request
from starlette.responses import Response

from lead_cleaner.api.error_handlers import register_error_handlers
from lead_cleaner.api.request_context import (
    REQUEST_ID_HEADER,
    get_request_id,
    reset_request_id,
    resolve_request_id,
    set_request_id,
)
from lead_cleaner.config import Settings
from lead_cleaner.observability import log_event
from lead_cleaner.rag.retriever import (
    CloseableRagRetriever,
    RagRetriever,
)
from lead_cleaner.rag.retriever_factory import create_rag_retriever
from lead_cleaner.schemas.lead import LeadProcessingResult, RawLeadInput
from lead_cleaner.services.feature_extractor import (
    CloseableFeatureExtractor,
    FeatureExtractor,
)
from lead_cleaner.services.feature_extractor_factory import create_feature_extractor
from lead_cleaner.services.processor import process_lead
from lead_cleaner.services.recommendation_generator import (
    CloseableRecommendationGenerator,
    RecommendationGenerator,
)
from lead_cleaner.services.recommendation_generator_factory import (
    create_recommendation_generator,
)


def create_app(*, settings: Settings | None = None) -> FastAPI:
    """Build the API and own one feature extractor for its full lifetime."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_settings = settings or Settings()
        feature_extractor = create_feature_extractor(resolved_settings)
        rag_retriever: RagRetriever | None = None
        recommendation_generator: RecommendationGenerator | None = None

        try:
            rag_retriever = create_rag_retriever(resolved_settings)
            recommendation_generator = create_recommendation_generator(resolved_settings)

            app.state.settings = resolved_settings
            app.state.feature_extractor = feature_extractor
            app.state.rag_retriever = rag_retriever
            app.state.recommendation_generator = recommendation_generator

            yield
        finally:
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
        return cast(FeatureExtractor, request.app.state.feature_extractor)

    def get_rag_retriever(request: Request) -> RagRetriever:
        return cast(RagRetriever, request.app.state.rag_retriever)

    def get_recommendation_generator(
        request: Request,
    ) -> RecommendationGenerator | None:
        return cast(
            RecommendationGenerator | None,
            request.app.state.recommendation_generator,
        )

    @api.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @api.post("/process-lead", response_model=LeadProcessingResult)
    def process_lead_api(
        raw_lead: RawLeadInput,
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
        return result

    return api


app = create_app()
