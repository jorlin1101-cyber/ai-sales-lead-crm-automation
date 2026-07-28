import logging

from lead_cleaner.observability import log_event
from lead_cleaner.rag.query_fusion import retrieve_queries_with_rrf
from lead_cleaner.rag.retrieval_intent import build_retrieval_queries
from lead_cleaner.rag.retriever import DisabledRagRetriever, RagRetriever
from lead_cleaner.rag.source_mapper import sanitize_retrieved_sources
from lead_cleaner.schemas.ai_output import LeadAnalysisResult
from lead_cleaner.schemas.lead import CleanedLead, KnowledgeSource
from lead_cleaner.services.llm_errors import LLMClientError
from lead_cleaner.services.recommendation_builder import (
    build_llm_grounded_recommendation,
    build_recommendation,
)
from lead_cleaner.services.recommendation_generator import RecommendationGenerator


def ground_analysis_with_rag(
    analysis_result: LeadAnalysisResult,
    cleaned_lead: CleanedLead,
    *,
    rag_retriever: RagRetriever | None = None,
    recommendation_generator: RecommendationGenerator | None = None,
) -> tuple[LeadAnalysisResult, list[KnowledgeSource]]:
    """Attach sources and a recommendation without recalculating Decision."""

    if analysis_result.decision.disposition == "spam":
        recommendation = build_recommendation(
            analysis_result,
            [],
            "skipped",
        )
        metadata = analysis_result.metadata.model_copy(
            update={
                "retrieval_method": "skipped",
                "recommendation_method": recommendation.recommendation_method,
            }
        )
        return (
            analysis_result.model_copy(
                update={
                    "recommended_action": recommendation.recommended_action,
                    "followup_email_draft": recommendation.followup_email_draft,
                    "metadata": metadata,
                }
            ),
            [],
        )

    retriever = rag_retriever or DisabledRagRetriever()
    queries = build_retrieval_queries(cleaned_lead, analysis_result.features)
    retrieval = retrieve_queries_with_rrf(retriever, queries)
    sources = sanitize_retrieved_sources(retrieval.chunks)

    if (
        recommendation_generator is not None
        and analysis_result.decision.disposition == "qualified"
        and not analysis_result.decision.needs_review
        and not analysis_result.security_signals.injection_suspected
        and not analysis_result.security_signals.knowledge_injection_suspected
        and retrieval.retrieval_method in {"keyword_rrf", "bge_rrf"}
        and bool(retrieval.chunks)
    ):
        try:
            draft = recommendation_generator.generate(
                cleaned_lead=cleaned_lead,
                analysis_result=analysis_result,
                chunks=retrieval.chunks,
            )
        except LLMClientError as error:
            log_event(
                "grounded_recommendation_fallback",
                level=logging.WARNING,
                recommendation_method="generic_template",
                error_code=error.error_code,
                error_type=type(error).__name__,
            )
            recommendation = build_recommendation(
                analysis_result,
                sources,
                retrieval.retrieval_method,
            )
        else:
            recommendation = build_llm_grounded_recommendation(draft)
            log_event(
                "grounded_recommendation_generated",
                recommendation_method=recommendation.recommendation_method,
                cited_source_count=len(draft.cited_chunk_ids),
            )
    else:
        recommendation = build_recommendation(
            analysis_result,
            sources,
            retrieval.retrieval_method,
        )

    metadata = analysis_result.metadata.model_copy(
        update={
            "retrieval_method": retrieval.retrieval_method,
            "recommendation_method": recommendation.recommendation_method,
        }
    )

    grounded_result = analysis_result.model_copy(
        update={
            "recommended_action": recommendation.recommended_action,
            "followup_email_draft": recommendation.followup_email_draft,
            "metadata": metadata,
        }
    )

    return grounded_result, sources
