from lead_cleaner.config import AppMode, LLMProvider, Settings
from lead_cleaner.services.demo_fixture_feature_extractor import (
    DemoFixtureFeatureExtractor,
)
from lead_cleaner.services.feature_extractor import FeatureExtractor
from lead_cleaner.services.live_feature_extractor import LiveFeatureExtractor
from lead_cleaner.services.llm_errors import LLMConfigurationError
from lead_cleaner.services.openai_feature_client import OpenAIFeatureClient
from lead_cleaner.services.rule_feature_extractor import RuleFeatureExtractor


def create_feature_extractor(settings: Settings) -> FeatureExtractor:
    """Create exactly one extractor for the validated application mode."""

    if settings.app_mode == AppMode.RULE_ONLY:
        return RuleFeatureExtractor()

    if settings.app_mode == AppMode.DEMO:
        return DemoFixtureFeatureExtractor(settings.demo_feature_fixtures_path)

    if settings.app_mode == AppMode.LIVE:
        if settings.llm_provider != LLMProvider.OPENAI:
            raise LLMConfigurationError(
                "The primary live execution path currently supports only LLM_PROVIDER=openai."
            )

        client = OpenAIFeatureClient.from_settings(settings)
        return LiveFeatureExtractor(client=client)

    raise LLMConfigurationError(f"Unsupported APP_MODE: {settings.app_mode}")
