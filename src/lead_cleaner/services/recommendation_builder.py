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


def _uses_chinese(analysis_result: LeadAnalysisResult) -> bool:
    return analysis_result.features.language == "zh"


def _build_followup_email(analysis_result: LeadAnalysisResult) -> str:
    """Create a safe deterministic draft for offline and fallback execution."""

    features = analysis_result.features
    missing_details: list[str] = []

    if not features.mentions_specific_dates:
        missing_details.append(
            "预计出行日期" if _uses_chinese(analysis_result) else "preferred travel dates"
        )
    if features.group_size is None:
        missing_details.append("同行人数" if _uses_chinese(analysis_result) else "group size")

    if _uses_chinese(analysis_result):
        details = "、".join(missing_details + ["预算范围", "特殊需求"])
        return (
            "主题：进一步确认您的行程需求\n\n"
            "您好：\n\n"
            "感谢您的咨询。为了便于我们准备更合适的行程方案与报价，"
            f"请您补充确认{details}。\n\n"
            "收到信息后，我们会根据您的需求整理下一步建议。\n\n"
            "祝好\n销售团队"
        )

    details = ", ".join(missing_details + ["budget range", "any special requirements"])
    return (
        "Subject: A few details about your travel inquiry\n\n"
        "Hello,\n\n"
        "Thank you for your inquiry. To prepare a suitable itinerary and quotation, "
        f"could you please confirm your {details}?\n\n"
        "Once we receive these details, we will prepare the recommended next steps.\n\n"
        "Best regards,\nSales Team"
    )


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
                "不要自动回复。保留疑似推广标记，仅在业务规则要求时进行人工复核。"
                if _uses_chinese(analysis_result)
                else "Do not send an automated reply. Keep the lead classified as spam and "
                "review only if required by business policy."
            ),
            recommendation_method="skipped",
        )

    if decision.needs_review:
        return RecommendationOutcome(
            recommended_action=(
                "请先人工复核原始咨询和风险提示，确认无误后再决定是否联系客户。"
                if _uses_chinese(analysis_result)
                else "Review the original inquiry and risk signals before deciding whether "
                "to contact the customer."
            ),
            recommendation_method="generic_template",
        )

    email_draft = _build_followup_email(analysis_result)

    if (
        analysis_result.metadata.execution_mode == "demo"
        and sources
        and retrieval_method in {"keyword_rrf", "bge_rrf"}
    ):
        source_labels = "; ".join(f"{source.source_title} — {source.section}" for source in sources)
        return RecommendationOutcome(
            recommended_action=(
                (
                    f"请结合右侧展示的 {len(sources)} 条知识依据准备有针对性的回复。"
                    "发送方案前，请确认出行日期、人数、预算和特殊需求。"
                )
                if _uses_chinese(analysis_result)
                else (
                    "Review the lead and prepare a tailored response using these retrieved "
                    f"knowledge sections: {source_labels}. Confirm dates, group details, "
                    "budget, and any special requirements before sending a proposal."
                )
            ),
            followup_email_draft=email_draft,
            recommendation_method="demo_template",
        )

    if decision.disposition == "qualified":
        action = (
            "优先安排人工跟进；准备方案前确认出行日期、人数、预算、资源可用性和特殊需求。"
            if _uses_chinese(analysis_result)
            else "Prioritize this lead for human follow-up. Confirm dates, group details, "
            "budget, availability, and special requirements before preparing a proposal."
        )
    elif decision.disposition == "nurture":
        action = (
            "将该线索加入人工审核的培育队列，补充关键行程信息后再准备方案。"
            if _uses_chinese(analysis_result)
            else "Add this lead to a human-reviewed nurture queue and request the missing trip "
            "details before preparing a proposal."
        )
    else:
        action = (
            "请先人工复核该线索，再决定是否跟进；不要自动发送回复。"
            if _uses_chinese(analysis_result)
            else "Review this lead manually before taking follow-up action. Do not send an "
            "automated reply."
        )

    return RecommendationOutcome(
        recommended_action=action,
        followup_email_draft=email_draft,
        recommendation_method="generic_template",
    )
