from typing import Literal, Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator

from lead_cleaner.config import AppMode
from lead_cleaner.schemas.ai_output import AnalysisMethod
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import LeadFeatures


FallbackReason = Literal[
    "timeout",
    "rate_limit",
    "provider_unavailable",
    "invalid_json",
    "schema_validation_error",
    "demo_fixture_not_found",
]


class FeatureExtractionOutcome(BaseModel):
    """Internal result returned by every feature extractor."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    features: LeadFeatures
    execution_mode: AppMode
    analysis_method: AnalysisMethod
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    fallback_reason: FallbackReason | None = None

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        llm_details = (
            self.provider,
            self.model,
            self.prompt_version,
        )

        if self.analysis_method == "llm_features":
            if self.execution_mode != AppMode.LIVE:
                raise ValueError("llm_features requires execution_mode=live")

            if any(value is None or not value.strip() for value in llm_details):
                raise ValueError("llm_features requires provider, model, and prompt_version")

            if self.fallback_reason is not None:
                raise ValueError("llm_features cannot have a fallback_reason")

            return self

        if any(value is not None for value in llm_details):
            raise ValueError("non-LLM feature outcomes cannot contain LLM provenance")

        if self.analysis_method == "demo_fixture":
            if self.execution_mode != AppMode.DEMO:
                raise ValueError("demo_fixture requires execution_mode=demo")

            if self.fallback_reason is not None:
                raise ValueError("demo_fixture cannot have a fallback_reason")

        return self


@runtime_checkable
class FeatureExtractor(Protocol):
    def extract(self, cleaned_lead: CleanedLead) -> FeatureExtractionOutcome:
        """Extract canonical lead features with truthful provenance."""
        ...


@runtime_checkable
class CloseableFeatureExtractor(FeatureExtractor, Protocol):
    """A feature extractor that owns a reusable external client."""

    def close(self) -> None:
        """Release resources owned by the extractor."""
        ...
