import httpx
import pytest
from types import SimpleNamespace
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from lead_cleaner.config import AppMode, LLMProvider, Settings
from lead_cleaner.schemas.policy import ExtractedLeadFeatures
from lead_cleaner.services import openai_feature_client
from lead_cleaner.services.llm_errors import (
    LLMAuthenticationError,
    LLMClientError,
    LLMConfigurationError,
    LLMInvalidJSONError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMResponseIncompleteError,
    LLMSchemaValidationError,
    LLMTimeoutError,
)
from lead_cleaner.services.openai_feature_client import OpenAIFeatureClient


class FakeResponse:
    def __init__(self, output_parsed):
        self.output_parsed = output_parsed


class FakeResponses:
    def __init__(self, *, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return self.response


class FakeOpenAI:
    def __init__(self, *, response=None, error: Exception | None = None):
        self.responses = FakeResponses(response=response, error=error)
        self.closed = False

    def close(self):
        self.closed = True


def make_features() -> ExtractedLeadFeatures:
    return ExtractedLeadFeatures(
        customer_kind="agency",
        group_size=20,
        mentions_specific_dates=True,
        asks_for_price=True,
        requests_private_or_custom_service=True,
        destinations=["Sichuan"],
        language="en",
    )


def make_live_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "app_mode": AppMode.LIVE,
        "allow_network": True,
        "llm_provider": LLMProvider.OPENAI,
        "openai_api_key": "test-key",
        "openai_model": "test-model",
        "llm_timeout_seconds": 12.5,
        "llm_max_retries": 1,
    }
    values.update(overrides)
    return Settings(**values)


def make_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/responses")


def make_status_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=make_request())


def test_from_settings_creates_reusable_client_with_reliability_options(monkeypatch):
    captured = {}
    fake_sdk_client = FakeOpenAI(response=FakeResponse(make_features()))

    def fake_openai_constructor(**kwargs):
        captured.update(kwargs)
        return fake_sdk_client

    monkeypatch.setattr(openai_feature_client, "OpenAI", fake_openai_constructor)
    settings = make_live_settings(openai_base_url="https://example.test/v1")

    client = OpenAIFeatureClient.from_settings(settings)

    assert client.provider == "openai"
    assert client.model == "test-model"
    assert captured == {
        "api_key": "test-key",
        "base_url": "https://example.test/v1",
        "timeout": 12.5,
        "max_retries": 1,
    }


@pytest.mark.parametrize("app_mode", [AppMode.DEMO, AppMode.RULE_ONLY])
def test_offline_modes_do_not_create_openai_client(monkeypatch, app_mode):
    def fail_if_called(**kwargs):
        raise AssertionError("OpenAI constructor must not be called")

    monkeypatch.setattr(openai_feature_client, "OpenAI", fail_if_called)
    settings = Settings(
        _env_file=None,
        app_mode=app_mode,
        allow_network=False,
    )

    with pytest.raises(LLMConfigurationError, match="APP_MODE=live"):
        OpenAIFeatureClient.from_settings(settings)


def test_non_openai_provider_is_rejected_before_client_creation(monkeypatch):
    def fail_if_called(**kwargs):
        raise AssertionError("OpenAI constructor must not be called")

    monkeypatch.setattr(openai_feature_client, "OpenAI", fail_if_called)
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        allow_network=True,
        llm_provider=LLMProvider.DEEPSEEK,
        deepseek_api_key="test-key",
        deepseek_model="test-model",
    )

    with pytest.raises(LLMConfigurationError, match="LLM_PROVIDER=openai"):
        OpenAIFeatureClient.from_settings(settings)


def test_extract_returns_restricted_features_and_separates_prompt_roles():
    expected = make_features()
    fake_sdk_client = FakeOpenAI(response=FakeResponse(expected))
    client = OpenAIFeatureClient(client=fake_sdk_client, model="test-model")

    result = client.extract("system instructions", "untrusted lead JSON")

    assert result == expected
    assert fake_sdk_client.responses.kwargs == {
        "model": "test-model",
        "input": [
            {"role": "system", "content": "system instructions"},
            {"role": "user", "content": "untrusted lead JSON"},
        ],
        "text_format": ExtractedLeadFeatures,
    }


@pytest.mark.parametrize(
    ("sdk_error", "expected_error"),
    [
        (APITimeoutError(make_request()), LLMTimeoutError),
        (
            RateLimitError(
                "rate limited",
                response=make_status_response(429),
                body=None,
            ),
            LLMRateLimitError,
        ),
        (
            APIConnectionError(request=make_request()),
            LLMProviderUnavailableError,
        ),
        (
            InternalServerError(
                "server error",
                response=make_status_response(500),
                body=None,
            ),
            LLMProviderUnavailableError,
        ),
        (
            AuthenticationError(
                "invalid key",
                response=make_status_response(401),
                body=None,
            ),
            LLMAuthenticationError,
        ),
        (
            BadRequestError(
                "bad request",
                response=make_status_response(400),
                body=None,
            ),
            LLMConfigurationError,
        ),
        (RuntimeError("unknown failure"), LLMClientError),
    ],
)
def test_extract_translates_sdk_errors(sdk_error, expected_error):
    fake_sdk_client = FakeOpenAI(error=sdk_error)
    client = OpenAIFeatureClient(client=fake_sdk_client, model="test-model")

    with pytest.raises(expected_error):
        client.extract("system prompt", "user prompt")


def test_extract_rejects_empty_structured_output():
    fake_sdk_client = FakeOpenAI(response=FakeResponse(None))
    client = OpenAIFeatureClient(client=fake_sdk_client, model="test-model")

    with pytest.raises(LLMInvalidJSONError):
        client.extract("system prompt", "user prompt")


def test_extract_rejects_incomplete_response():
    response = FakeResponse(None)
    response.status = "incomplete"
    response.incomplete_details = SimpleNamespace(reason="max_output_tokens")
    response.output = []
    fake_sdk_client = FakeOpenAI(response=response)
    client = OpenAIFeatureClient(client=fake_sdk_client, model="test-model")

    with pytest.raises(LLMResponseIncompleteError, match="max_output_tokens"):
        client.extract("system prompt", "user prompt")


def test_extract_rejects_refusal_nested_in_message_content():
    response = FakeResponse(None)
    response.status = "completed"
    response.output = [
        SimpleNamespace(
            type="message",
            content=[SimpleNamespace(type="refusal", refusal="Cannot comply")],
        )
    ]
    fake_sdk_client = FakeOpenAI(response=response)
    client = OpenAIFeatureClient(client=fake_sdk_client, model="test-model")

    with pytest.raises(LLMRefusalError):
        client.extract("system prompt", "user prompt")


def test_extract_rejects_invalid_structured_schema():
    fake_sdk_client = FakeOpenAI(response=FakeResponse({"customer_kind": "vip"}))
    client = OpenAIFeatureClient(client=fake_sdk_client, model="test-model")

    with pytest.raises(LLMSchemaValidationError):
        client.extract("system prompt", "user prompt")


def test_blank_model_is_rejected():
    fake_sdk_client = FakeOpenAI(response=FakeResponse(make_features()))

    with pytest.raises(LLMConfigurationError, match="cannot be blank"):
        OpenAIFeatureClient(client=fake_sdk_client, model="   ")


def test_close_closes_underlying_sdk_client():
    fake_sdk_client = FakeOpenAI(response=FakeResponse(make_features()))
    client = OpenAIFeatureClient(client=fake_sdk_client, model="test-model")

    client.close()

    assert fake_sdk_client.closed is True
