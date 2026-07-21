from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lead_cleaner.api import main as api_main
from lead_cleaner.api.main import create_app
from lead_cleaner.config import AppMode, LLMProvider, RagBackend, Settings
from lead_cleaner.rag.retriever import RagRetrievalOutcome
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import ExtractedLeadFeatures
from lead_cleaner.services import feature_extractor_factory
from lead_cleaner.services.feature_extractor import FeatureExtractionOutcome
from lead_cleaner.services.llm_errors import (
    LLMAuthenticationError,
    LLMClientError,
    LLMConfigurationError,
)
from lead_cleaner.services.rule_feature_extractor import RuleFeatureExtractor


FIXTURE_PATH = Path("data/demo/lead_feature_fixtures.json")
VALID_PAYLOAD = {
    "external_lead_id": "sample-lead-001",
    "name": "Test Lead",
    "email": "test@example.com",
    "company_name": "Example Travel Agency",
    "message": "We need a private Sichuan tour quotation for 20 clients.",
    "source": "Website",
}


class TrackingFeatureExtractor:
    def __init__(self) -> None:
        self.extract_calls = 0
        self.close_calls = 0

    def extract(self, cleaned_lead: CleanedLead) -> FeatureExtractionOutcome:
        self.extract_calls += 1
        return RuleFeatureExtractor().extract(cleaned_lead)

    def close(self) -> None:
        self.close_calls += 1


class TrackingRagRetriever:
    def __init__(self) -> None:
        self.retrieve_calls = 0
        self.close_calls = 0

    def retrieve(self, query: str) -> RagRetrievalOutcome:
        self.retrieve_calls += 1
        return RagRetrievalOutcome(retrieval_method="disabled")

    def close(self) -> None:
        self.close_calls += 1


class FakeLiveClient:
    provider = "openai"
    model = "test-model"

    def __init__(self) -> None:
        self.close_calls = 0

    def extract(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> ExtractedLeadFeatures:
        return ExtractedLeadFeatures(
            customer_kind="agency",
            group_size=20,
            asks_for_price=True,
            requests_private_or_custom_service=True,
            language="en",
        )

    def close(self) -> None:
        self.close_calls += 1


class FakeOpenAIFeatureClientFactory:
    client = FakeLiveClient()

    @classmethod
    def from_settings(cls, settings: Settings) -> FakeLiveClient:
        return cls.client


class RaisingFeatureExtractor:
    def __init__(self, error: LLMClientError) -> None:
        self.error = error

    def extract(self, cleaned_lead: CleanedLead) -> FeatureExtractionOutcome:
        raise self.error


def fail_if_openai_client_is_created(*args, **kwargs):
    raise AssertionError("Offline application modes must not create an OpenAI client")


def test_application_creates_one_extractor_reuses_it_and_closes_it(monkeypatch):
    extractor = TrackingFeatureExtractor()
    rag_retriever = TrackingRagRetriever()
    factory_calls = 0
    rag_factory_calls = 0

    def fake_factory(settings: Settings):
        nonlocal factory_calls
        factory_calls += 1
        return extractor

    def fake_rag_factory(settings: Settings):
        nonlocal rag_factory_calls
        rag_factory_calls += 1
        return rag_retriever

    monkeypatch.setattr(api_main, "create_feature_extractor", fake_factory)
    monkeypatch.setattr(api_main, "create_rag_retriever", fake_rag_factory)
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.RULE_ONLY,
        allow_network=False,
    )

    with TestClient(create_app(settings=settings)) as client:
        first_response = client.post("/process-lead", json=VALID_PAYLOAD)
        second_response = client.post("/process-lead", json=VALID_PAYLOAD)

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert factory_calls == 1
        assert rag_factory_calls == 1
        assert extractor.extract_calls == 2
        assert rag_retriever.retrieve_calls == 2
        assert extractor.close_calls == 0
        assert rag_retriever.close_calls == 0

    assert extractor.close_calls == 1
    assert rag_retriever.close_calls == 1


@pytest.mark.parametrize(
    ("app_mode", "expected_execution_mode"),
    [
        (AppMode.DEMO, "demo"),
        (AppMode.RULE_ONLY, "rule_only"),
    ],
)
def test_offline_application_modes_never_construct_openai_client(
    monkeypatch,
    app_mode,
    expected_execution_mode,
):
    monkeypatch.setattr(
        feature_extractor_factory.OpenAIFeatureClient,
        "from_settings",
        fail_if_openai_client_is_created,
    )
    settings = Settings(
        _env_file=None,
        app_mode=app_mode,
        allow_network=False,
        openai_api_key="real-looking-key-must-not-be-used",
        openai_model="real-looking-model",
        demo_feature_fixtures_path=FIXTURE_PATH,
        rag_backend=RagBackend.DISABLED,
    )

    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/process-lead", json=VALID_PAYLOAD)

    assert response.status_code == 200
    assert response.json()["analysis_result"]["metadata"]["execution_mode"] == (
        expected_execution_mode
    )


def test_live_application_uses_fake_client_and_closes_it(monkeypatch):
    fake_factory = FakeOpenAIFeatureClientFactory
    fake_factory.client = FakeLiveClient()
    monkeypatch.setattr(
        feature_extractor_factory,
        "OpenAIFeatureClient",
        fake_factory,
    )
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        allow_network=True,
        llm_provider=LLMProvider.OPENAI,
        openai_api_key="test-key",
        openai_model="test-model",
        rag_backend=RagBackend.DISABLED,
    )

    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/process-lead", json=VALID_PAYLOAD)

        assert response.status_code == 200
        metadata = response.json()["analysis_result"]["metadata"]
        assert metadata["execution_mode"] == "live"
        assert metadata["analysis_method"] == "llm_features"
        assert metadata["provider"] == "openai"
        assert fake_factory.client.close_calls == 0

    assert fake_factory.client.close_calls == 1


def test_unsupported_live_provider_fails_during_application_startup():
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        allow_network=True,
        llm_provider=LLMProvider.DEEPSEEK,
        deepseek_api_key="test-key",
        deepseek_model="test-model",
        rag_backend=RagBackend.DISABLED,
    )

    with pytest.raises(
        LLMConfigurationError,
        match="currently supports only LLM_PROVIDER=openai",
    ):
        with TestClient(create_app(settings=settings)):
            pass


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (LLMAuthenticationError("secret provider text"), 503, "authentication_error"),
        (LLMConfigurationError("secret provider text"), 503, "configuration_error"),
        (LLMClientError("secret provider text"), 500, "internal_error"),
    ],
)
def test_non_fallback_llm_errors_return_safe_transport_errors(
    monkeypatch,
    error,
    expected_status,
    expected_code,
):
    monkeypatch.setattr(
        api_main,
        "create_feature_extractor",
        lambda settings: RaisingFeatureExtractor(error),
    )
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.RULE_ONLY,
        allow_network=False,
        rag_backend=RagBackend.DISABLED,
    )

    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/process-lead", json=VALID_PAYLOAD)

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    assert "secret provider text" not in response.text
