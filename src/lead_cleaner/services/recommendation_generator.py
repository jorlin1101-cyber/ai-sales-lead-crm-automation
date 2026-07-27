from typing import Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.ai_output import LeadAnalysisResult
from lead_cleaner.schemas.lead import CleanedLead


class GroundedRecommendationDraft(BaseModel):
    """Internal LLM output; cited IDs are validated before anything is exposed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recommended_action: str = Field(min_length=1, max_length=1000)
    followup_email_draft: str = Field(min_length=1, max_length=2000)
    # A grounded recommendation intentionally requires at least one evidence ID.
    cited_chunk_ids: list[str] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_unique_citations(self) -> Self:
        if len(self.cited_chunk_ids) != len(set(self.cited_chunk_ids)):
            raise ValueError("cited_chunk_ids cannot contain duplicates")
        return self


@runtime_checkable
class RecommendationGenerator(Protocol):
    def generate(
        self,
        *,
        cleaned_lead: CleanedLead,
        analysis_result: LeadAnalysisResult,
        chunks: list[RetrievedChunk],
    ) -> GroundedRecommendationDraft:
        """Generate one structured recommendation grounded in retrieved chunks."""
        ...


@runtime_checkable
class CloseableRecommendationGenerator(RecommendationGenerator, Protocol):
    def close(self) -> None:
        """Release resources owned by the recommendation generator."""
        ...
