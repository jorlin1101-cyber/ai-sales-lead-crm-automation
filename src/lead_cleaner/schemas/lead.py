from typing import Literal, Self
from pydantic import BaseModel, ConfigDict, Field, model_validator
from lead_cleaner.schemas.ai_output import LeadAnalysisResult


ValidationErrorCode = Literal[
    "empty_email",
    "invalid_email_format",
    "empty_message_after_cleaning",
]


class RawLeadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_lead_id: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=200)
    email: str = Field(max_length=320)
    company_name: str | None = Field(default=None, max_length=300)
    message: str = Field(min_length=1, max_length=5000)
    source: str | None = Field(default="Unknown", max_length=100)


class CleanedLead(BaseModel):
    lead_id: str
    external_lead_id: str | None = None
    name: str
    email: str
    company_name: str
    message: str
    source: str


class LeadValidationResult(BaseModel):
    is_valid: bool
    error_codes: list[ValidationErrorCode] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        if self.is_valid and self.error_codes:
            raise ValueError("A valid result requires error_codes=[]")

        if not self.is_valid and not self.error_codes:
            raise ValueError("An invalid result requires at least one error code")

        return self


class KnowledgeSource(BaseModel):
    chunk_id: str
    source_title: str
    section: str
    rank: int = Field(ge=1, le=3)


class LeadProcessingResult(BaseModel):
    cleaned_lead: CleanedLead
    validation_result: LeadValidationResult
    analysis_result: LeadAnalysisResult | None = None
    sources: list[KnowledgeSource] = Field(default_factory=list)
