import pytest

from lead_cleaner.config import AppMode
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import ExtractedLeadFeatures
from lead_cleaner.services import live_feature_extractor
from lead_cleaner.services.feature_extractor import FeatureExtractor
from lead_cleaner.services.live_feature_extractor import (
    LLMFeatureClient,
    LiveFeatureExtractor,
)
from lead_cleaner.services.llm_errors import (
    LLMAuthenticationError,
    LLMClientError,
    LLMConfigurationError,
    LLMInvalidJSONError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMSchemaValidationError,
    LLMTimeoutError,
)


class FakeLLMFeatureClient:
    provider = "openai"
    model = "test-model"

    def __init__(
        self,
        *,
        features: ExtractedLeadFeatures | None = None,
        error: Exception | None = None,
    ) -> None:
        self.features = features
        self.error = error
        self.calls: list[tuple[str, str]] = []
        self.close_calls = 0

    def extract(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> ExtractedLeadFeatures:
        self.calls.append((system_prompt, user_prompt))

        if self.error is not None:
            raise self.error

        if self.features is None:
            raise AssertionError("Fake client requires features or an error")

        return self.features

    def close(self) -> None:
        self.close_calls += 1


def make_cleaned_lead() -> CleanedLead:
    return CleanedLead(
        lead_id="lead-live-test",
        external_lead_id="external-live-test",
        name="Test Lead",
        email="test@example.com",
        company_name="Example Travel Agency",
        message="We need a private Sichuan tour quotation for 20 clients.",
        source="Website",
    )


def make_extracted_features() -> ExtractedLeadFeatures:
    return ExtractedLeadFeatures(
        customer_kind="agency",
        group_size=20,
        asks_for_price=True,
        requests_private_or_custom_service=True,
        destinations=["Sichuan"],
        language="en",
    )


def test_live_success_returns_canonical_features_and_truthful_provenance(monkeypatch):
    client = FakeLLMFeatureClient(features=make_extracted_features())
    extractor = LiveFeatureExtractor(client=client, language="zh")
    cleaned_lead = make_cleaned_lead()

    monkeypatch.setattr(
        live_feature_extractor,
        "get_lead_feature_system_prompt",
        lambda language: f"system-{language}",
    )
    monkeypatch.setattr(
        live_feature_extractor,
        "build_lead_feature_prompt",
        lambda lead, language: f"user-{language}-{lead.external_lead_id}",
    )

    outcome = extractor.extract(cleaned_lead)

    assert client.calls == [("system-zh", "user-zh-external-live-test")]
    assert outcome.execution_mode == AppMode.LIVE
    assert outcome.analysis_method == "llm_features"
    assert outcome.provider == "openai"
    assert outcome.model == "test-model"
    assert outcome.prompt_version == "lead-features-v1"
    assert outcome.fallback_reason is None
    assert outcome.features.customer_kind == "agency"
    assert outcome.features.company_name_present is True
    assert outcome.features.cleaned_message_length == len(cleaned_lead.message)


@pytest.mark.parametrize(
    ("error", "expected_reason"),
    [
        (LLMTimeoutError("timeout"), "timeout"),
        (LLMRateLimitError("rate limit"), "rate_limit"),
        (
            LLMProviderUnavailableError("unavailable"),
            "provider_unavailable",
        ),
        (LLMInvalidJSONError("invalid JSON"), "invalid_json"),
        (
            LLMSchemaValidationError("invalid schema"),
            "schema_validation_error",
        ),
    ],
)
def test_approved_runtime_errors_use_rule_fallback(error, expected_reason):
    client = FakeLLMFeatureClient(error=error)
    extractor = LiveFeatureExtractor(client=client)

    outcome = extractor.extract(make_cleaned_lead())

    assert outcome.execution_mode == AppMode.LIVE
    assert outcome.analysis_method == "rule_features"
    assert outcome.fallback_reason == expected_reason
    assert outcome.provider is None
    assert outcome.model is None
    assert outcome.prompt_version is None
    assert outcome.features.customer_kind == "agency"


@pytest.mark.parametrize(
    "error",
    [
        LLMAuthenticationError("invalid key"),
        LLMConfigurationError("invalid configuration"),
        LLMClientError("unknown client failure"),
    ],
)
def test_non_fallback_errors_continue_upward(error):
    client = FakeLLMFeatureClient(error=error)
    extractor = LiveFeatureExtractor(client=client)

    with pytest.raises(type(error)):
        extractor.extract(make_cleaned_lead())


def test_live_extractor_and_fake_client_match_common_protocols():
    client = FakeLLMFeatureClient(features=make_extracted_features())
    extractor = LiveFeatureExtractor(client=client)

    assert isinstance(client, LLMFeatureClient)
    assert isinstance(extractor, FeatureExtractor)


def test_live_extractor_closes_its_reusable_client():
    client = FakeLLMFeatureClient(features=make_extracted_features())
    extractor = LiveFeatureExtractor(client=client)

    extractor.close()

    assert client.close_calls == 1
