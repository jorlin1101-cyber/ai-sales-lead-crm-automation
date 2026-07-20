from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lead_cleaner.schemas.policy import LeadDecision, LeadFeatures, SecuritySignals


AnalysisMethod = Literal["llm_features", "demo_fixture", "rule_features"]
RecommendationMethod = Literal[
    "llm_grounded",
    "demo_template",
    "generic_template",
    "skipped",
]
RetrievalMethod = Literal[
    "keyword_rrf",
    "bge_rrf",
    "disabled",
    "unavailable",
    "skipped",
]


class AnalysisMetadata(BaseModel):
    """Server-owned provenance for one lead analysis."""

    model_config = ConfigDict(extra="forbid")

    analysis_method: AnalysisMethod
    recommendation_method: RecommendationMethod
    retrieval_method: RetrievalMethod
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    fallback_reason: str | None = None


class LeadAnalysisResult(BaseModel):
    """Public analysis contract with facts, security signals, and policy output."""

    model_config = ConfigDict(extra="forbid")

    features: LeadFeatures
    security_signals: SecuritySignals
    decision: LeadDecision
    lead_summary: str = Field(min_length=1)
    recommended_action: str = Field(min_length=1)
    followup_email_draft: str
    metadata: AnalysisMetadata
