import pytest
from pydantic import ValidationError

from lead_cleaner.config import AppMode
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import LeadFeatures
from lead_cleaner.services.feature_extractor import (
    FeatureExtractionOutcome,
    FeatureExtractor,
)


def make_features() -> LeadFeatures:
    return LeadFeatures(
        customer_kind="agency",
        asks_for_price=True,
        company_name_present=True,
        cleaned_message_length=100,
    )


def test_rule_outcome_accepts_rule_only_mode() -> None:
    outcome = FeatureExtractionOutcome(
        features=make_features(),
        execution_mode=AppMode.RULE_ONLY,
        analysis_method="rule_features",
    )

    assert outcome.analysis_method == "rule_features"
    assert outcome.provider is None
    assert outcome.fallback_reason is None


def test_live_llm_outcome_requires_complete_provenance() -> None:
    outcome = FeatureExtractionOutcome(
        features=make_features(),
        execution_mode=AppMode.LIVE,
        analysis_method="llm_features",
        provider="openai",
        model="test-model",
        prompt_version="lead-features-v1",
    )

    assert outcome.execution_mode == AppMode.LIVE
    assert outcome.provider == "openai"


@pytest.mark.parametrize(
    "missing_field",
    [
        "provider",
        "model",
        "prompt_version",
    ],
)
def test_llm_outcome_rejects_missing_provenance(
    missing_field: str,
) -> None:
    payload = {
        "features": make_features(),
        "execution_mode": AppMode.LIVE,
        "analysis_method": "llm_features",
        "provider": "openai",
        "model": "test-model",
        "prompt_version": "lead-features-v1",
    }
    payload[missing_field] = None

    with pytest.raises(
        ValidationError,
        match="requires provider, model, and prompt_version",
    ):
        FeatureExtractionOutcome.model_validate(payload)


def test_llm_outcome_rejects_demo_mode() -> None:
    with pytest.raises(
        ValidationError,
        match="llm_features requires execution_mode=live",
    ):
        FeatureExtractionOutcome(
            features=make_features(),
            execution_mode=AppMode.DEMO,
            analysis_method="llm_features",
            provider="openai",
            model="test-model",
            prompt_version="lead-features-v1",
        )


def test_demo_fixture_requires_demo_mode() -> None:
    with pytest.raises(
        ValidationError,
        match="demo_fixture requires execution_mode=demo",
    ):
        FeatureExtractionOutcome(
            features=make_features(),
            execution_mode=AppMode.LIVE,
            analysis_method="demo_fixture",
        )


def test_non_llm_outcome_rejects_llm_provenance() -> None:
    with pytest.raises(
        ValidationError,
        match="cannot contain LLM provenance",
    ):
        FeatureExtractionOutcome(
            features=make_features(),
            execution_mode=AppMode.RULE_ONLY,
            analysis_method="rule_features",
            provider="openai",
        )


class StubFeatureExtractor:
    def extract(self, cleaned_lead: CleanedLead) -> FeatureExtractionOutcome:
        return FeatureExtractionOutcome(
            features=make_features(),
            execution_mode=AppMode.RULE_ONLY,
            analysis_method="rule_features",
        )


def test_structural_implementation_matches_protocol() -> None:
    extractor = StubFeatureExtractor()

    assert isinstance(extractor, FeatureExtractor)
