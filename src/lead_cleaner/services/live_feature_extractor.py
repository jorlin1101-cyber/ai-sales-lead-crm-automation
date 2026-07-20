from typing import Protocol, runtime_checkable

from lead_cleaner.config import AppMode
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import ExtractedLeadFeatures
from lead_cleaner.services.feature_extractor import FeatureExtractionOutcome
from lead_cleaner.services.lead_feature_merger import (
    merge_extracted_features_with_server_facts,
)
from lead_cleaner.services.llm_errors import LLMClientError, LLMFallbackError
from lead_cleaner.services.prompt_builder import (
    FEATURE_PROMPT_VERSION,
    FeaturePromptLanguage,
    build_lead_feature_prompt,
    get_lead_feature_system_prompt,
)
from lead_cleaner.services.rule_feature_extractor import RuleFeatureExtractor


@runtime_checkable
class LLMFeatureClient(Protocol):
    provider: str
    model: str

    def extract(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> ExtractedLeadFeatures:
        """Return only the constrained features supplied by one LLM provider."""
        ...

    def close(self) -> None:
        """Release resources owned by the provider client."""
        ...


class LiveFeatureExtractor:
    """Use a live LLM for facts and deterministic rules for approved fallbacks."""

    def __init__(
        self,
        *,
        client: LLMFeatureClient,
        language: FeaturePromptLanguage = "en",
    ) -> None:
        self._client = client
        self._language = language

    def extract(
        self,
        cleaned_lead: CleanedLead,
    ) -> FeatureExtractionOutcome:
        system_prompt = get_lead_feature_system_prompt(self._language)
        user_prompt = build_lead_feature_prompt(
            cleaned_lead,
            language=self._language,
        )

        try:
            extracted_features = self._client.extract(
                system_prompt,
                user_prompt,
            )
        except LLMFallbackError as error:
            fallback_reason = error.fallback_reason
            if fallback_reason is None:
                raise LLMClientError(
                    "Fallback-eligible LLM error did not provide a fallback reason."
                ) from error

            rule_fallback = RuleFeatureExtractor(
                execution_mode=AppMode.LIVE,
                fallback_reason=fallback_reason,
            )
            return rule_fallback.extract(cleaned_lead)

        features = merge_extracted_features_with_server_facts(
            extracted_features,
            cleaned_lead,
        )

        return FeatureExtractionOutcome(
            features=features,
            execution_mode=AppMode.LIVE,
            analysis_method="llm_features",
            provider=self._client.provider,
            model=self._client.model,
            prompt_version=FEATURE_PROMPT_VERSION,
        )

    def close(self) -> None:
        self._client.close()
