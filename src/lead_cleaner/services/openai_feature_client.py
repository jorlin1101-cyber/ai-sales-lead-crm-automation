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
from lead_cleaner.schemas.policy import ExtractedLeadFeatures
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


class OpenAIFeatureClient:
    """Extract constrained lead features through one reusable OpenAI client."""

    provider = "openai"

    def __init__(self, *, client: OpenAI, model: str) -> None:
        normalized_model = model.strip()
        if not normalized_model:
            raise LLMConfigurationError("OPENAI_MODEL cannot be blank.")

        self._client = client
        self.model = normalized_model

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        if settings.app_mode != AppMode.LIVE:
            raise LLMConfigurationError("OpenAIFeatureClient can only be created in APP_MODE=live.")

        if settings.llm_provider != LLMProvider.OPENAI:
            raise LLMConfigurationError("OpenAIFeatureClient requires LLM_PROVIDER=openai.")

        if settings.openai_api_key is None or settings.openai_model is None:
            raise LLMConfigurationError("OPENAI_API_KEY and OPENAI_MODEL are required.")

        base_url = (settings.openai_base_url or "").strip() or None
        client = OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

        return cls(client=client, model=settings.openai_model)

    def extract(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> ExtractedLeadFeatures:
        try:
            response = self._client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                text_format=ExtractedLeadFeatures,
            )
        except APITimeoutError as error:
            raise LLMTimeoutError("OpenAI feature extraction timed out.") from error
        except RateLimitError as error:
            raise LLMRateLimitError("OpenAI rate limit exceeded.") from error
        except (APIConnectionError, InternalServerError) as error:
            raise LLMProviderUnavailableError("OpenAI is temporarily unavailable.") from error
        except AuthenticationError as error:
            raise LLMAuthenticationError("OpenAI authentication failed.") from error
        except BadRequestError as error:
            raise LLMConfigurationError(
                "OpenAI rejected the configured model or request."
            ) from error
        except ValidationError as error:
            raise LLMSchemaValidationError(
                "OpenAI feature output failed schema validation."
            ) from error
        except Exception as error:
            raise LLMClientError("Unexpected OpenAI client failure.") from error

        ensure_complete_structured_response(
            response,
            operation="OpenAI feature extraction",
        )

        parsed_result = response.output_parsed
        if parsed_result is None:
            raise LLMInvalidJSONError("OpenAI returned empty structured feature output.")

        try:
            return ExtractedLeadFeatures.model_validate(parsed_result)
        except ValidationError as error:
            raise LLMSchemaValidationError(
                "OpenAI feature output failed schema validation."
            ) from error

    def close(self) -> None:
        self._client.close()
