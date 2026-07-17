from typing import Literal
from pydantic import BaseModel, Field
from lead_cleaner.schemas.ai_output import LeadAnalysisResult

class RawLeadInput(BaseModel):
    name: str | None = None
    email: str
    company_name: str | None = None
    message: str = Field(min_length=1)
    source: str = "Unknown"


class CleanedLead(BaseModel):
    lead_id: str
    name: str
    email: str
    company_name: str
    message: str
    source: str


class LeadValidationResult(BaseModel):
    is_valid: bool
    error_reason: Literal[
        "valid",
        "empty_email",
        "empty_message",
        "invalid_email_format",
    ]


class LeadScoreResult(BaseModel):
    lead_type: Literal["B2B", "B2C", "Unknown"]
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


class LeadProcessingResult(BaseModel):
    cleaned_lead: CleanedLead
    validation_result: LeadValidationResult
    analysis_result: LeadAnalysisResult | None = None
