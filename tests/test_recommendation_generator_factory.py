from lead_cleaner.config import AppMode, Settings
from lead_cleaner.services import recommendation_generator_factory
from lead_cleaner.services.recommendation_generator_factory import (
    create_recommendation_generator,
)


def test_factory_returns_none_when_feature_is_disabled() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.RULE_ONLY,
        allow_network=False,
        grounded_recommendation_enabled=False,
    )

    assert create_recommendation_generator(settings) is None


def test_factory_creates_generator_only_when_enabled(monkeypatch) -> None:
    sentinel = object()
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        allow_network=True,
        openai_api_key="test-key",
        openai_model="test-model",
        grounded_recommendation_enabled=True,
    )

    monkeypatch.setattr(
        recommendation_generator_factory.OpenAIRecommendationGenerator,
        "from_settings",
        lambda received_settings: (
            sentinel if received_settings is settings else AssertionError("wrong settings")
        ),
    )

    assert create_recommendation_generator(settings) is sentinel
