from pydantic import BaseModel, Field

from typing import Literal

class LeadAnalysisResult(BaseModel):
    lead_type : Literal["B2B","B2C","Unknown"]
    lead_subtype: Literal[
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
    intent_level: Literal["High", "Medium", "Low", "Unknown"]
    lead_score: int = Field(ge=0, le=100)
    lead_summary: str = Field(min_length=1)
    recommended_action: str = Field(min_length=1)
    followup_email_draft: str
    analysis_method: Literal["llm", "rule_fallback"]
    confidence: float = Field(ge=0, le=1)
