import pytest
from pydantic import ValidationError

from lead_cleaner.services.recommendation_generator import (
    GroundedRecommendationDraft,
)


def test_grounded_recommendation_draft_accepts_bounded_evidence() -> None:
    draft = GroundedRecommendationDraft(
        recommended_action="Confirm the travel window before preparing a quotation.",
        followup_email_draft="Thank you. Could you confirm your preferred travel dates?",
        cited_chunk_ids=["chunk-1", "chunk-2"],
    )

    assert draft.cited_chunk_ids == ["chunk-1", "chunk-2"]


def test_grounded_recommendation_draft_requires_a_citation() -> None:
    with pytest.raises(ValidationError):
        GroundedRecommendationDraft(
            recommended_action="Confirm the travel window.",
            followup_email_draft="Could you confirm your travel dates?",
            cited_chunk_ids=[],
        )


def test_grounded_recommendation_draft_rejects_duplicate_citations() -> None:
    with pytest.raises(ValidationError, match="cannot contain duplicates"):
        GroundedRecommendationDraft(
            recommended_action="Confirm the travel window.",
            followup_email_draft="Could you confirm your travel dates?",
            cited_chunk_ids=["chunk-1", "chunk-1"],
        )


def test_grounded_recommendation_draft_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        GroundedRecommendationDraft.model_validate(
            {
                "recommended_action": "Confirm the travel window.",
                "followup_email_draft": "Could you confirm your travel dates?",
                "cited_chunk_ids": ["chunk-1"],
                "lead_score": 100,
            }
        )
