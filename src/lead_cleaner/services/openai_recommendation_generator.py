from typing import Self

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from pydantic import ValidationError

from lead_cleaner.config import AppMode, LLMProvider, Settings
from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.ai_output import LeadAnalysisResult
from lead_cleaner.schemas.lead import CleanedLead
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
from lead_cleaner.services.openai_response_guard import (
    ensure_complete_structured_response,
)
from lead_cleaner.services.recommendation_generator import (
    GroundedRecommendationDraft,
)
from lead_cleaner.services.recommendation_prompt_builder import (
    RECOMMENDATION_PROMPT_VERSION,
    build_recommendation_prompt,
    choose_recommendation_prompt_language,
    get_recommendation_system_prompt,
)


class OpenAIRecommendationGenerator:
    """Generate one evidence-constrained recommendation through a reusable client."""

    provider = "openai"
    prompt_version = RECOMMENDATION_PROMPT_VERSION

    def __init__(
        self,
        *,
        client: OpenAI,
        model: str,
        max_output_tokens: int = 1024,
    ) -> None:
        normalized_model = model.strip()
        if not normalized_model:
            raise LLMConfigurationError("OPENAI_MODEL cannot be blank.")
        if max_output_tokens < 256 or max_output_tokens > 2048:
            raise LLMConfigurationError(
                "RECOMMENDATION_MAX_OUTPUT_TOKENS must be between 256 and 2048."
            )

        self._client = client
        self.model = normalized_model
        self.max_output_tokens = max_output_tokens

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        if not settings.grounded_recommendation_enabled:
            raise LLMConfigurationError(
                "OpenAIRecommendationGenerator requires GROUNDED_RECOMMENDATION_ENABLED=true."
            )
        if settings.app_mode != AppMode.LIVE:
            raise LLMConfigurationError(
                "OpenAIRecommendationGenerator can only be created in APP_MODE=live."
            )
        if settings.llm_provider != LLMProvider.OPENAI:
            raise LLMConfigurationError(
                "OpenAIRecommendationGenerator requires LLM_PROVIDER=openai."
            )
        if settings.openai_api_key is None or settings.openai_model is None:
            raise LLMConfigurationError("OPENAI_API_KEY and OPENAI_MODEL are required.")

        base_url = (settings.openai_base_url or "").strip() or None
        client = OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        return cls(
            client=client,
            model=settings.openai_model,
            max_output_tokens=settings.recommendation_max_output_tokens,
        )

    def generate(
        self,
        *,
        cleaned_lead: CleanedLead,
        analysis_result: LeadAnalysisResult,
        chunks: list[RetrievedChunk],
    ) -> GroundedRecommendationDraft:
        if not chunks:
            raise LLMSchemaValidationError(
                "Grounded recommendation requires at least one retrieved chunk."
            )

        language = choose_recommendation_prompt_language(
            analysis_result.features.language,
            cleaned_lead.message,
        )
        system_prompt = get_recommendation_system_prompt(language)
        user_prompt = build_recommendation_prompt(
            cleaned_lead,
            analysis_result,
            chunks,
            language=language,
        )

        try:
            response = self._client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                text_format=GroundedRecommendationDraft,
                max_output_tokens=self.max_output_tokens,
            )
        except APITimeoutError as error:
            raise LLMTimeoutError("OpenAI recommendation generation timed out.") from error
        except RateLimitError as error:
            raise LLMRateLimitError("OpenAI rate limit exceeded.") from error
        except (APIConnectionError, InternalServerError) as error:
            raise LLMProviderUnavailableError("OpenAI is temporarily unavailable.") from error
        except AuthenticationError as error:
            raise LLMAuthenticationError("OpenAI authentication failed.") from error
        except BadRequestError as error:
            raise LLMConfigurationError(
                "OpenAI rejected the configured recommendation model or request."
            ) from error
        except ValidationError as error:
            raise LLMSchemaValidationError(
                "OpenAI recommendation output failed schema validation."
            ) from error
        except Exception as error:
            raise LLMClientError("Unexpected OpenAI recommendation client failure.") from error

        ensure_complete_structured_response(
            response,
            operation="OpenAI recommendation generation",
        )

        parsed_result = response.output_parsed
        if parsed_result is None:
            raise LLMInvalidJSONError("OpenAI returned empty structured recommendation output.")

        try:
            draft = GroundedRecommendationDraft.model_validate(parsed_result)
        except ValidationError as error:
            raise LLMSchemaValidationError(
                "OpenAI recommendation output failed schema validation."
            ) from error

        allowed_chunk_ids = {chunk.chunk_id for chunk in chunks}
        unknown_chunk_ids = set(draft.cited_chunk_ids) - allowed_chunk_ids
        if unknown_chunk_ids:
            raise LLMSchemaValidationError(
                "OpenAI recommendation cited chunks that were not retrieved."
            )

        return draft

    def close(self) -> None:
        self._client.close()
