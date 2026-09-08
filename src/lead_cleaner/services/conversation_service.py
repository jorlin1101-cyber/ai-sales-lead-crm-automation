from __future__ import annotations

import re
import hashlib
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.rag.retriever import RagRetriever, ProductManualRetriever
from lead_cleaner.rag.source_mapper import sanitize_retrieved_sources
from lead_cleaner.schemas.conversation import (
    ConversationFact,
    ConversationMessageRequest,
    ConversationRetrievalTrace,
    ConversationState,
    ConversationTurnResult,
    ReplyDraft,
)
from lead_cleaner.schemas.lead import RawLeadInput
from lead_cleaner.services.conversation_store import (
    ConversationStore,
    ConversationMessageProcessingError,
)
from lead_cleaner.services.conversation_rag import (
    ContextualRagRetriever,
    build_conversation_context_query,
    route_conversation_retrieval,
)
from lead_cleaner.services.conversation_reply_composer import (
    ConversationKnowledgePlan,
    build_knowledge_plan,
    compose_grounded_reply,
    select_grounding_chunks,
)
from lead_cleaner.services.feature_extractor import FeatureExtractor
from lead_cleaner.services.processor import process_lead
from lead_cleaner.services.policy_v1 import evaluate_policy
from lead_cleaner.services.conversation_memory import OPT_OUT, merge_facts, cumulative_features
from lead_cleaner.services.rule_feature_extractor import RuleFeatureExtractor
from lead_cleaner.services.service_preferences import extract_preferences
from lead_cleaner.services.recommendation_generator import RecommendationGenerator
from lead_cleaner.services.conversation_slots import (
    enrich_facts,
    missing_fields,
    conversation_language,
    UNRESOLVED,
    REGIONS,
)
from lead_cleaner.services.product_recommendation import (
    recommend_product,
    product_questions,
    attach_product,
)
from lead_cleaner.services.conversation_llm import (
    QwenConversationLLM,
    ConversationLLMError,
    apply_understanding,
)


_DATE_PATTERN = re.compile(
    r"(?:20\d{2}[年/-])?\d{1,2}[月/-]\d{1,2}(?:日|号)?"
    r"(?:\s*(?:到|至|[-–])\s*(?:20\d{2}[年/-])?\d{1,2}"
    r"(?:[月/-]\d{1,2})?(?:日|号)?)?"
)
_BUDGET_PATTERN = re.compile(
    r"(?:预算|每人|人均|budget|per\s+person)\D{0,12}"
    r"(?:[¥￥$]\s*)?[\d,]+(?:\.\d+)?\s*(?:元|人民币|CNY|RMB|USD|美元)?",
    re.IGNORECASE,
)
_FACT_LABELS = {
    "travel_date": ("出行日期", "travel dates"),
    "group_size": ("同行人数", "group size"),
    "destination": ("目的地", "destination"),
    "budget": ("预算范围", "budget range"),
    "special_requirements": ("特殊需求", "special requirements"),
    "hotel_tier": ("酒店等级", "hotel tier"),
    "vehicle": ("用车需求", "vehicle"),
    "guide_language": ("导游语言", "guide language"),
}

_ZH_VALUE_LABELS = {
    "Western Sichuan": "川西",
    "Sichuan": "四川",
    "Chengdu": "成都",
    "Tibet": "西藏",
}


def _synthetic_email(conversation_id: str) -> str:
    stable = uuid5(NAMESPACE_URL, conversation_id).hex[:16]
    return f"conversation-{stable}@example.com"


def _extract_facts(
    request: ConversationMessageRequest, result: Any, message_id: str
) -> list[ConversationFact]:
    features = result.analysis_result.features if result.analysis_result else None
    if features is None:
        return []
    message = request.message
    facts: list[ConversationFact] = []
    if features.group_size is not None:
        corrected = re.search(
            r"(?:改成|改为|更正为|actually)\s*(\d+)\s*(?:个?人|people)", message, re.I
        )
        facts.append(
            ConversationFact(
                key="group_size",
                value=corrected.group(1) if corrected else str(features.group_size),
                status="customer_confirmed",
                confidence=0.95,
                source_message_id=message_id,
            )
        )
    if features.destinations:
        facts.append(
            ConversationFact(
                key="destination",
                value=features.destinations[0],
                status="inferred",
                confidence=0.85,
                source_message_id=message_id,
            )
        )
    date_match = _DATE_PATTERN.search(message)
    if date_match:
        facts.append(
            ConversationFact(
                key="travel_date",
                value=date_match.group(0),
                status="customer_confirmed",
                confidence=0.9,
                source_message_id=message_id,
            )
        )
    budget_match = _BUDGET_PATTERN.search(message)
    if budget_match:
        facts.append(
            ConversationFact(
                key="budget",
                value=budget_match.group(0).strip(),
                status="customer_confirmed",
                confidence=0.85,
                source_message_id=message_id,
            )
        )
    facts.extend(extract_preferences(message, message_id))
    if re.search(r"(?:没有|无|暂无)\s*(?:特殊需求|特殊要求|忌口)|no\s+special", message, re.I):
        facts.append(
            ConversationFact(
                key="special_requirements",
                value="无",
                status="customer_confirmed",
                confidence=0.9,
                source_message_id=message_id,
            )
        )
    return facts


def _open_questions(
    facts: list[ConversationFact],
    *,
    language: str,
    plan: ConversationKnowledgePlan,
) -> list[str]:
    return missing_fields(facts, pricing="pricing" in plan.intents, language=language)


def _fact_text(facts: list[ConversationFact], *, language: str) -> str:
    visible = [fact for fact in facts if fact.status not in UNRESOLVED]
    if not visible:
        return ""
    if language == "zh":
        labels = {key: value[0] for key, value in _FACT_LABELS.items()}
        return "；".join(
            f"{labels.get(fact.key, fact.key)}：{_ZH_VALUE_LABELS.get(fact.value, fact.value)}"
            for fact in visible
        )
    labels = {key: value[1] for key, value in _FACT_LABELS.items()}
    return "; ".join(f"{labels.get(fact.key, fact.key)}: {fact.value}" for fact in visible)


def _render_reply(
    request: ConversationMessageRequest,
    *,
    conversation_id: str,
    turn_number: int,
    result: Any,
    facts: list[ConversationFact],
    open_questions: list[str],
    plan: ConversationKnowledgePlan,
    grounding_chunks: list[RetrievedChunk],
    language: str | None = None,
) -> ReplyDraft:
    analysis = result.analysis_result
    content = compose_grounded_reply(
        request,
        facts=facts,
        open_questions=open_questions,
        plan=plan,
        chunks=grounding_chunks,
        language=language,
    )
    needs_review = bool(analysis and analysis.decision.needs_review) or any(
        fact.status == "conflicted" for fact in facts
    )
    status: Literal["needs_human_review", "ready_for_review"] = (
        "needs_human_review" if needs_review else "ready_for_review"
    )
    return ReplyDraft(
        draft_id=f"draft_{uuid4().hex}",
        channel=request.channel,
        conversation_id=conversation_id,
        turn_number=turn_number,
        status=status,
        subject=content.subject,
        body_text=content.body_text,
        display_text=content.body_text,
        open_questions=open_questions,
        source_ids=content.cited_chunk_ids,
        generation_method=content.generation_method,
        answer_intents=list(plan.intents),
        policy_version=analysis.decision.policy_version if analysis else "policy-v1",
        evidence=[
            {
                "chunk_id": chunk.chunk_id,
                "source_title": chunk.source_title,
                "section": chunk.section,
                "text": chunk.text,
                "sha256": hashlib.sha256(chunk.text.encode()).hexdigest(),
            }
            for chunk in grounding_chunks
            if chunk.chunk_id in content.cited_chunk_ids
        ],
        internal_note=(
            "部分资料未提供当前版本中文译文，请复核原文。"
            if "译文待复核" in content.body_text
            else None
        ),
    )


class ConversationService:
    def __init__(self, store: ConversationStore) -> None:
        self.store = store

    def process_message(
        self,
        request: ConversationMessageRequest,
        *,
        feature_extractor: FeatureExtractor,
        rag_retriever: RagRetriever,
        recommendation_generator: RecommendationGenerator | None,
        conversation_llm: QwenConversationLLM | None = None,
    ) -> ConversationTurnResult:
        if request.account_id != "default":
            namespace = hashlib.sha256(
                f"{request.source}\0{request.account_id}".encode()
            ).hexdigest()
            request = request.model_copy(update={"source": f"account-{namespace}"})
        summary = self.store.get_or_create_conversation(request)
        with self.store.processing_lease(summary.conversation_id) as token:
            duplicate = self.store.find_message_result(
                channel=request.channel,
                source=request.source,
                external_message_id=request.external_message_id,
                subject=request.subject,
                text=request.message,
                request=request,
            )
            if duplicate:
                return duplicate
            previous = self.store.latest_result(summary.conversation_id)
            previous_facts = self.store.get_facts(summary.conversation_id)
            # Repair only previously missing preference slots from customer messages.
            # Never mine assistant drafts or replace human-confirmed/conflicted facts.
            recovered: list[ConversationFact] = []
            for item in self.store.timeline(summary.conversation_id):
                if item.direction == "inbound" and item.processing_status == "processed":
                    recovered = merge_facts(
                        recovered, extract_preferences(item.text, item.message_id), item.text
                    )
            existing_keys = {fact.key for fact in previous_facts}
            previous_facts.extend(fact for fact in recovered if fact.key not in existing_keys)
            recent_messages = self.store.get_recent_messages(summary.conversation_id)
            message_id, turn_number = self.store.append_message(
                conversation_id=summary.conversation_id,
                external_message_id=request.external_message_id,
                channel=request.channel,
                source=request.source,
                subject=request.subject,
                text=request.message,
                recover=True,
            )
            try:
                return self._process_turn(
                    request,
                    summary=summary,
                    token=token,
                    message_id=message_id,
                    turn_number=turn_number,
                    previous=previous,
                    previous_facts=previous_facts,
                    recent_messages=recent_messages,
                    feature_extractor=feature_extractor,
                    rag_retriever=rag_retriever,
                    conversation_llm=conversation_llm,
                )
            except Exception:
                try:
                    self.store.mark_failed(message_id, summary.conversation_id, token)
                except ConversationMessageProcessingError:
                    pass  # A newer lease owns this message; never modify its state.
                raise

    def _process_turn(
        self,
        request: ConversationMessageRequest,
        *,
        summary: Any,
        token: str,
        message_id: str,
        turn_number: int,
        previous: ConversationTurnResult | None,
        previous_facts: list[ConversationFact],
        recent_messages: list[str],
        feature_extractor: FeatureExtractor,
        rag_retriever: RagRetriever,
        conversation_llm: QwenConversationLLM | None = None,
    ) -> ConversationTurnResult:
        opted_out = summary.state == "do_not_contact" or bool(OPT_OUT.search(request.message))
        raw = RawLeadInput(
            external_lead_id=summary.conversation_id,
            name=request.sender_name,
            email=request.sender_email or _synthetic_email(summary.conversation_id),
            company_name=request.company_name,
            message=request.message,
            source=request.source,
        )
        # Extract once. Expensive retrieval/generation happens only after the policy gate.
        result = process_lead(
            raw,
            feature_extractor=RuleFeatureExtractor()
            if opted_out or conversation_llm
            else feature_extractor,
        )
        analysis = result.analysis_result
        message_score = analysis.decision.lead_score if analysis else None
        language = conversation_language(
            request.message, previous.reply_language if previous else "zh"
        )
        previous_questions = previous.open_questions if previous else []
        incoming = enrich_facts(
            request.message,
            message_id,
            _extract_facts(request, result, message_id),
            previous_questions,
        )
        llm_trace = {
            "provider": "dashscope" if conversation_llm else "none",
            "model": conversation_llm.model if conversation_llm else "none",
            "understanding": "not_called",
            "generation": "not_called",
        }
        safe_for_model = not opted_out and bool(
            analysis
            and analysis.decision.disposition != "spam"
            and not analysis.security_signals.injection_suspected
        )
        if conversation_llm and safe_for_model:
            try:
                understanding = conversation_llm.understand(
                    request.message, previous_facts, previous_questions, recent_messages
                )
                previous_facts, incoming = apply_understanding(
                    previous_facts, incoming, understanding, message_id
                )
                llm_trace["understanding"] = "succeeded"
            except ConversationLLMError as error:
                llm_trace["understanding"] = "fallback:" + error.code
        facts = merge_facts(previous_facts, incoming, request.message)
        if analysis:
            prior = previous.current_analysis.analysis_result if previous else None
            features = cumulative_features(
                prior.features if prior else None, analysis.features, facts
            )
            analysis = analysis.model_copy(
                update={
                    "features": features,
                    "decision": evaluate_policy(features, analysis.security_signals),
                }
            )
            result = result.model_copy(update={"analysis_result": analysis})
        suppressed = opted_out or bool(analysis and analysis.decision.disposition == "spam")
        security_blocked = bool(
            analysis
            and (
                analysis.security_signals.injection_suspected
                or analysis.security_signals.knowledge_injection_suspected
            )
        )
        plan = build_knowledge_plan(request.message)
        current_plan = plan
        route = route_conversation_retrieval(request.message)
        if plan.intents == ("information_collection",) and previous and route.decision != "skipped":
            plan = build_knowledge_plan(" ".join(previous.reply_draft.answer_intents))
        destination = next(
            (f.value for f in facts if f.key == "destination" and f.status not in UNRESOLVED), None
        )
        product_requested = route.decision == "required" and (
            bool({"product_overview", "itinerary"}.intersection(plan.intents))
            or (
                bool(destination)
                and (
                    "pricing" in plan.intents
                    or (bool(incoming) and current_plan.intents == ("information_collection",))
                )
            )
        )
        product = None
        chunks: list[RetrievedChunk] = []
        queries: list[str] = []
        method = "skipped"
        reason = route.reason
        decision = route.decision
        if suppressed or security_blocked:
            decision, reason = "blocked", "do_not_contact" if opted_out else "policy_gate"
        elif route.decision == "required":
            retriever = ContextualRagRetriever(
                base=rag_retriever,
                context_query=build_conversation_context_query(
                    current_message=request.message, facts=facts, recent_messages=recent_messages
                ),
            )
            try:
                retriever.retrieve_focus(request.message)
                outcome = retriever.retrieve_focus(plan.focus_query)
                chunks = select_grounding_chunks(
                    retriever.captured_chunks, plan, language=language, destination=destination
                )
                method = outcome.retrieval_method
                if product_requested and isinstance(rag_retriever, ProductManualRetriever):
                    region = REGIONS.get(destination or "")
                    manuals = rag_retriever.product_manuals(region) if region else []
                    retriever.queries.append(
                        f"product manual lookup: region={region or 'unspecified'}; sections=Suitable For, Typical Duration, Key Experiences"
                    )
                    product, product_chunks = recommend_product(manuals, facts, language)
                    if product:
                        extras = (
                            chunks
                            if "pricing" in plan.intents or "permit_payment" in plan.intents
                            else [
                                c
                                for c in manuals
                                if c.notion_page_id == product_chunks[0].notion_page_id
                                and c.section == "Key Experiences"
                            ]
                        )
                        extra = next(
                            (
                                c
                                for c in extras
                                if c.chunk_id not in product.source_ids
                                and (
                                    c.doc_type != "product"
                                    or c.notion_page_id == product_chunks[0].notion_page_id
                                )
                            ),
                            None,
                        )
                        chunks = product_chunks + ([extra] if extra else [])
            except Exception:
                method, reason = "unavailable", "retrieval_unavailable"
            queries = retriever.queries
        if product_requested and not product:
            chunks = [
                chunk
                for chunk in chunks
                if chunk.region == "general" and chunk.doc_type != "product"
            ]
        sources = sanitize_retrieved_sources(chunks)
        if analysis:
            analysis = analysis.model_copy(
                update={
                    "metadata": analysis.metadata.model_copy(update={"retrieval_method": method})
                }
            )
        result = result.model_copy(update={"sources": sources, "analysis_result": analysis})
        questions = [] if suppressed else _open_questions(facts, language=language, plan=plan)
        if product_requested and not suppressed and "pricing" not in plan.intents:
            questions = product_questions(facts, language)
        draft = _render_reply(
            request,
            conversation_id=summary.conversation_id,
            turn_number=turn_number,
            result=result,
            facts=facts,
            open_questions=questions,
            plan=plan,
            grounding_chunks=chunks,
            language=language,
        )
        if product:
            draft = attach_product(draft, product, language, chunks)
            if plan.intents == ("information_collection",):
                draft = draft.model_copy(update={"answer_intents": ["product_overview"]})
        elif product_requested and decision == "required":
            note = (
                "当前产品手册尚未检索到与该目的地匹配的完整产品，暂时不能给出具体产品推荐。"
                if language == "zh"
                else "The current manuals do not contain a complete matching product for this destination, so I cannot recommend a specific product yet."
            )
            body = note + "\n\n" + draft.body_text
            draft = draft.model_copy(
                update={"body_text": body, "display_text": body, "internal_note": note}
            )
        if (
            conversation_llm
            and safe_for_model
            and not security_blocked
            and chunks
            and (current_plan.intents != ("information_collection",) or product is not None)
            and (not product_requested or product is not None)
            and llm_trace["understanding"] == "succeeded"
        ):
            try:
                draft = conversation_llm.compose(request, draft, facts, chunks, language)
                llm_trace["generation"] = "succeeded"
            except ConversationLLMError as error:
                llm_trace["generation"] = "fallback:" + error.code
        if any(value.startswith("fallback:") for value in llm_trace.values()):
            draft = draft.model_copy(
                update={
                    "internal_note": "本轮模型处理未完成，已使用规则/模板保留草稿，请人工复核。 / Model fallback; review required."
                }
            )
        if decision == "required" and not chunks:
            draft = draft.model_copy(
                update={
                    "internal_note": "本轮缺少可用知识依据，需人工核实产品和报价规则。 / No usable evidence; verify product and pricing rules manually."
                }
            )
        requires_review = (
            bool(analysis and analysis.decision.needs_review)
            or any(fact.status == "conflicted" for fact in facts)
            or bool(draft.internal_note)
        )
        state: ConversationState = (
            "do_not_contact"
            if suppressed
            else "needs_human_review"
            if requires_review
            else "waiting_customer"
            if questions
            else "ready_for_review"
        )
        if suppressed:
            draft = draft.model_copy(
                update={
                    "status": "suppressed",
                    "body_text": "",
                    "display_text": "",
                    "source_ids": [],
                    "evidence": [],
                    "internal_note": "已停止回复与跟进 / Reply and follow-up suppressed.",
                }
            )
        elif requires_review:
            draft = draft.model_copy(update={"status": "needs_human_review"})
        trace = ConversationRetrievalTrace(
            decision=decision,
            reason=reason,
            queries=queries,
            retrieval_method=method,
            sources=sources,
        )
        response = ConversationTurnResult(
            conversation_id=summary.conversation_id,
            turn_number=turn_number,
            state=state,
            idempotency_status="created",
            current_analysis=result,
            confirmed_facts=facts,
            open_questions=questions,
            reply_draft=draft,
            retrieval=trace,
            requires_human_review=requires_review,
            message_score=message_score,
            reply_language=language,
            llm_trace=llm_trace,
        )
        self.store.save_turn(
            conversation_id=summary.conversation_id,
            message_id=message_id,
            result=response,
            draft=draft,
            retrieval=trace,
            state=state,
            context_summary=_fact_text(facts, language=language),
            facts=facts,
            lease_token=token,
        )
        return response
