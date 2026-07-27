from lead_cleaner.config import Settings
from lead_cleaner.services.openai_recommendation_generator import (
    OpenAIRecommendationGenerator,
)
from lead_cleaner.services.recommendation_generator import RecommendationGenerator


def create_recommendation_generator(
    settings: Settings,
) -> RecommendationGenerator | None:
    """Create the optional live generator after Settings has validated its boundary."""

    if not settings.grounded_recommendation_enabled:
        return None

    return OpenAIRecommendationGenerator.from_settings(settings)
