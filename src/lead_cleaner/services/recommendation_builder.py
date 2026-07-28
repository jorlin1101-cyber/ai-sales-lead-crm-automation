from pydantic import BaseModel, ConfigDict, Field

from lead_cleaner.schemas.ai_output import (
    LeadAnalysisResult,
    RecommendationMethod,
    RetrievalMethod,
)
from lead_cleaner.schemas.lead import KnowledgeSource
from lead_cleaner.services.recommendation_generator import (
    GroundedRecommendationDraft,
)


class RecommendationOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    recommended_action: str = Field(min_length=1)
    followup_email_draft: str = ""
    recommendation_method: RecommendationMethod


def build_llm_grounded_recommendation(
    draft: GroundedRecommendationDraft,
) -> RecommendationOutcome:
    """Convert a validated internal draft into the existing public fields."""

    return RecommendationOutcome(
        recommended_action=draft.recommended_action,
        followup_email_draft=draft.followup_email_draft,
        recommendation_method="llm_grounded",
    )


def build_recommendation(
    analysis_result: LeadAnalysisResult,
    sources: list[KnowledgeSource],
    retrieval_method: RetrievalMethod,
) -> RecommendationOutcome:
    """Build a deterministic recommendation without changing LeadDecision."""

    decision = analysis_result.decision

    if decision.disposition == "spam":
        return RecommendationOutcome(
            recommended_action=(
                "Do not send an automated reply. Keep the lead classified as spam and "
                "review only if required by business policy."
            ),
            recommendation_method="skipped",
        )

    if (
        analysis_result.metadata.execution_mode == "demo"
        and sources
        and retrieval_method in {"keyword_rrf", "bge_rrf"}
    ):
        source_labels = "; ".join(f"{source.source_title} — {source.section}" for source in sources)
        return RecommendationOutcome(
            recommended_action=(
                "Review the lead and prepare a tailored response using these retrieved "
                f"knowledge sections: {source_labels}. Confirm dates, group details, "
                "budget, and any special requirements before sending a proposal."
            ),
            recommendation_method="demo_template",
        )

    if decision.disposition == "qualified":
        action = (
            "Prioritize this lead for human follow-up. Confirm dates, group details, "
            "budget, availability, and special requirements before preparing a proposal."
        )
    elif decision.disposition == "nurture":
        action = (
            "Add this lead to a human-reviewed nurture queue and request the missing trip "
            "details before preparing a proposal."
        )
    else:
        action = (
            "Review this lead manually before taking follow-up action. Do not send an "
            "automated reply."
        )

    return RecommendationOutcome(
        recommended_action=action,
        recommendation_method="generic_template",
    )
