from typing import Literal

from lead_cleaner.services.feature_extractor import FallbackReason


LLMErrorCode = Literal[
    "configuration_error",
    "authentication_error",
    "timeout",
    "rate_limit",
    "provider_unavailable",
    "invalid_json",
    "schema_validation_error",
    "internal_error",
]


class LLMClientError(Exception):
    """Base error for failures in the LLM feature-extraction boundary."""

    error_code: LLMErrorCode = "internal_error"
    fallback_reason: FallbackReason | None = None

    @property
    def can_fallback(self) -> bool:
        return self.fallback_reason is not None


class LLMFallbackError(LLMClientError):
    """Base class for runtime failures that may use deterministic rules."""


class LLMTimeoutError(LLMFallbackError):
    error_code: LLMErrorCode = "timeout"
    fallback_reason: FallbackReason = "timeout"


class LLMRateLimitError(LLMFallbackError):
    error_code: LLMErrorCode = "rate_limit"
    fallback_reason: FallbackReason = "rate_limit"


class LLMProviderUnavailableError(LLMFallbackError):
    error_code: LLMErrorCode = "provider_unavailable"
    fallback_reason: FallbackReason = "provider_unavailable"


class LLMInvalidJSONError(LLMFallbackError):
    error_code: LLMErrorCode = "invalid_json"
    fallback_reason: FallbackReason = "invalid_json"


class LLMSchemaValidationError(LLMFallbackError):
    error_code: LLMErrorCode = "schema_validation_error"
    fallback_reason: FallbackReason = "schema_validation_error"


class LLMAuthenticationError(LLMClientError):
    error_code: LLMErrorCode = "authentication_error"


class LLMConfigurationError(LLMClientError):
    error_code: LLMErrorCode = "configuration_error"
