from pathlib import Path

import pytest

from lead_cleaner.config import AppMode, LLMProvider, Settings
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import ExtractedLeadFeatures
from lead_cleaner.services import feature_extractor_factory
from lead_cleaner.services.demo_fixture_feature_extractor import (
    DemoFixtureFeatureExtractor,
)
from lead_cleaner.services.feature_extractor_factory import (
    create_feature_extractor,
)
from lead_cleaner.services.live_feature_extractor import LiveFeatureExtractor
from lead_cleaner.services.llm_errors import LLMConfigurationError
from lead_cleaner.services.rule_feature_extractor import RuleFeatureExtractor


FIXTURE_PATH = Path("data/demo/lead_feature_fixtures.json")


class FakeLiveClient:
    provider = "openai"
    model = "test-model"

    def extract(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> ExtractedLeadFeatures:
        return ExtractedLeadFeatures(
            customer_kind="agency",
            asks_for_price=True,
            language="en",
        )

    def close(self) -> None:
        pass


class FakeOpenAIFeatureClientFactory:
    captured_settings: Settings | None = None
    client = FakeLiveClient()

    @classmethod
    def from_settings(cls, settings: Settings) -> FakeLiveClient:
        cls.captured_settings = settings
        return cls.client


def make_cleaned_lead(
    *,
    external_lead_id: str | None = "sample-lead-001",
) -> CleanedLead:
    return CleanedLead(
        lead_id="lead-factory-test",
        external_lead_id=external_lead_id,
        name="Test Lead",
        email="test@example.com",
        company_name="Example Travel Agency",
        message="We need a private Chengdu tour quotation.",
        source="Website",
    )


def fail_if_live_client_is_created(*args, **kwargs):
    raise AssertionError("Offline modes must not create an OpenAI client")


@pytest.mark.parametrize(
    ("app_mode", "expected_type"),
    [
        (AppMode.DEMO, DemoFixtureFeatureExtractor),
        (AppMode.RULE_ONLY, RuleFeatureExtractor),
    ],
)
def test_offline_modes_never_create_openai_client(
    monkeypatch,
    app_mode,
    expected_type,
):
    monkeypatch.setattr(
        feature_extractor_factory.OpenAIFeatureClient,
        "from_settings",
        fail_if_live_client_is_created,
    )
    settings = Settings(
        _env_file=None,
        app_mode=app_mode,
        allow_network=False,
        openai_api_key="real-looking-key-must-not-be-used",
        openai_model="real-looking-model",
        demo_feature_fixtures_path=FIXTURE_PATH,
    )

    extractor = create_feature_extractor(settings)

    assert isinstance(extractor, expected_type)


def test_demo_factory_result_uses_fixture():
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.DEMO,
        allow_network=False,
        demo_feature_fixtures_path=FIXTURE_PATH,
    )
    extractor = create_feature_extractor(settings)

    outcome = extractor.extract(make_cleaned_lead())

    assert outcome.execution_mode == AppMode.DEMO
    assert outcome.analysis_method == "demo_fixture"


def test_rule_only_factory_result_uses_rules():
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.RULE_ONLY,
        allow_network=False,
    )
    extractor = create_feature_extractor(settings)

    outcome = extractor.extract(make_cleaned_lead(external_lead_id=None))

    assert outcome.execution_mode == AppMode.RULE_ONLY
    assert outcome.analysis_method == "rule_features"


def test_live_openai_builds_live_extractor(monkeypatch):
    monkeypatch.setattr(
        feature_extractor_factory,
        "OpenAIFeatureClient",
        FakeOpenAIFeatureClientFactory,
    )
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        allow_network=True,
        llm_provider=LLMProvider.OPENAI,
        openai_api_key="test-key",
        openai_model="test-model",
    )

    extractor = create_feature_extractor(settings)
    outcome = extractor.extract(make_cleaned_lead())

    assert isinstance(extractor, LiveFeatureExtractor)
    assert FakeOpenAIFeatureClientFactory.captured_settings is settings
    assert outcome.execution_mode == AppMode.LIVE
    assert outcome.analysis_method == "llm_features"
    assert outcome.provider == "openai"


def test_live_deepseek_is_explicitly_unsupported():
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        allow_network=True,
        llm_provider=LLMProvider.DEEPSEEK,
        deepseek_api_key="test-key",
        deepseek_model="test-model",
    )

    with pytest.raises(
        LLMConfigurationError,
        match="currently supports only LLM_PROVIDER=openai",
    ):
        create_feature_extractor(settings)
