import pytest

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


@pytest.mark.parametrize(
    ("error_type", "expected_code", "expected_reason"),
    [
        (LLMTimeoutError, "timeout", "timeout"),
        (LLMRateLimitError, "rate_limit", "rate_limit"),
        (
            LLMProviderUnavailableError,
            "provider_unavailable",
            "provider_unavailable",
        ),
        (LLMInvalidJSONError, "invalid_json", "invalid_json"),
        (
            LLMSchemaValidationError,
            "schema_validation_error",
            "schema_validation_error",
        ),
    ],
)
def test_fallback_errors_expose_stable_reason(
    error_type: type[LLMClientError],
    expected_code: str,
    expected_reason: str,
) -> None:
    error = error_type("test failure")

    assert error.error_code == expected_code
    assert error.fallback_reason == expected_reason


@pytest.mark.parametrize(
    ("error_type", "expected_code"),
    [
        (LLMAuthenticationError, "authentication_error"),
        (LLMConfigurationError, "configuration_error"),
    ],
)
def test_non_fallback_errors_are_not_silently_downgraded(
    error_type: type[LLMClientError],
    expected_code: str,
) -> None:
    error = error_type("test failure")

    assert error.error_code == expected_code
    assert error.fallback_reason is None


def test_error_message_is_preserved() -> None:
    error = LLMTimeoutError("provider took too long")

    assert str(error) == "provider took too long"
