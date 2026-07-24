from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


CustomerKind = Literal[
    "agency",
    "operator",
    "school",
    "corporate",
    "influencer",
    "individual",
    "unknown",
]

LeadType = Literal["B2B", "B2C", "Unknown"]

LeadSubtype = Literal[
    "Agency",
    "Operator",
    "School",
    "Corporate",
    "Influencer",
    "LargeGroup",
    "PrivateCustom",
    "LuxuryHighBudget",
    "FIT",
    "Other",
    "Unknown",
]

DecisionIntentLevel = Literal["High", "Medium", "Low"]

Disposition = Literal["qualified", "nurture", "spam", "manual_review"]

FeatureLanguage = Literal["en", "zh", "mixed", "unknown"]

ScoreComponentName = Literal[
    "spam_override",
    "customer_fit",
    "intent_strength",
    "order_value_proxy",
    "information_completeness",
]

ShortCode = Annotated[str, Field(min_length=1, max_length=100)]
Destination = Annotated[str, Field(min_length=1, max_length=100)]


class ExtractedLeadFeatures(BaseModel):
    """Business facts that a constrained feature extractor may provide."""

    model_config = ConfigDict(extra="forbid")

    customer_kind: CustomerKind
    group_size: int | None = Field(default=None, ge=1, le=10000)
    mentions_specific_dates: bool = False
    asks_for_price: bool = False
    asks_for_availability: bool = False
    requests_private_or_custom_service: bool = False
    requests_partnership: bool = False
    contains_spam_or_promotion: bool = False
    destinations: list[Destination] = Field(default_factory=list, max_length=10)
    language: FeatureLanguage = "unknown"


class LeadFeatures(ExtractedLeadFeatures):
    """Canonical features after server-owned facts have been added."""

    # These facts are derived by the server from CleanedLead, not trusted from an LLM.
    company_name_present: bool = False
    cleaned_message_length: int = Field(default=0, ge=0, le=5000)
    conflict_codes: list[ShortCode] = Field(default_factory=list, max_length=10)


class SecuritySignals(BaseModel):
    """Deterministic review signals; these are not definitive attack verdicts."""

    model_config = ConfigDict(extra="forbid")

    injection_suspected: bool = False
    matched_pattern_codes: list[ShortCode] = Field(default_factory=list, max_length=10)
    knowledge_injection_suspected: bool = False


class ScoreComponent(BaseModel):
    """One auditable line item in a policy score breakdown."""

    model_config = ConfigDict(extra="forbid")

    component: ScoreComponentName
    points: int = Field(ge=0, le=100)
    max_points: int = Field(ge=0, le=100)
    reason_codes: list[ShortCode] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_points_do_not_exceed_maximum(self) -> Self:
        if self.points > self.max_points:
            raise ValueError("points cannot exceed max_points")

        return self


class LeadDecision(BaseModel):
    """The complete, versioned output produced by the deterministic policy."""

    model_config = ConfigDict(extra="forbid")

    lead_type: LeadType
    lead_subtype: LeadSubtype
    disposition: Disposition
    intent_level: DecisionIntentLevel
    lead_score: int = Field(ge=0, le=100)
    score_breakdown: list[ScoreComponent] = Field(min_length=1, max_length=4)
    needs_review: bool
    review_reasons: list[ShortCode] = Field(default_factory=list, max_length=10)
    policy_version: str = Field(
        min_length=1,
        max_length=50,
        pattern=r"^policy-v[1-9][0-9]*$",
    )

    @model_validator(mode="after")
    def validate_structural_consistency(self) -> Self:
        component_names = [item.component for item in self.score_breakdown]
        if len(component_names) != len(set(component_names)):
            raise ValueError("score_breakdown cannot contain duplicate components")

        breakdown_total = sum(item.points for item in self.score_breakdown)
        if breakdown_total != self.lead_score:
            raise ValueError("score_breakdown points must sum to lead_score")

        if self.needs_review and not self.review_reasons:
            raise ValueError("needs_review=True requires at least one review reason")

        if not self.needs_review and self.review_reasons:
            raise ValueError("needs_review=False requires review_reasons=[]")

        if self.disposition == "manual_review" and not self.needs_review:
            raise ValueError("manual_review disposition requires needs_review=True")

        return self
