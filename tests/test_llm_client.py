import json

import pytest

from lead_cleaner.schemas.policy import ExtractedLeadFeatures
from lead_cleaner.services import llm_client
from lead_cleaner.services.llm_client import LLMClientError


class FakeResponse:
    def __init__(self, output_parsed):
        self.output_parsed = output_parsed


class FakeResponses:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs

        if self.error:
            raise self.error

        return self.response


class FakeClient:
    def __init__(self, responses):
        self.responses = responses


class FakeChatMessage:
    def __init__(self, content):
        self.content = content


class FakeChatChoice:
    def __init__(self, content):
        self.message = FakeChatMessage(content)


class FakeChatResponse:
    def __init__(self, content):
        self.choices = [FakeChatChoice(content)]


class FakeChatCompletions:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs

        if self.error:
            raise self.error

        return self.response


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeDeepSeekClient:
    def __init__(self, completions):
        self.chat = FakeChat(completions)


def make_valid_extracted_features() -> ExtractedLeadFeatures:
    return ExtractedLeadFeatures(
        customer_kind="agency",
        group_size=20,
        mentions_specific_dates=True,
        asks_for_price=True,
        requests_private_or_custom_service=True,
        destinations=["Sichuan"],
        language="en",
    )


def test_get_openai_client_missing_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(LLMClientError):
        llm_client.get_openai_client()


def test_get_openai_model_missing_model(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    with pytest.raises(LLMClientError):
        llm_client.get_openai_model()


def test_get_openai_model_returns_model(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "test_model")

    model = llm_client.get_openai_model()
    assert model == "test_model"


def test_get_openai_model_returns_deepseek_model(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    model = llm_client.get_openai_model()
    assert model == "deepseek-v4-flash"


def test_is_deepseek_configured_from_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")

    assert llm_client.is_deepseek_configured("some-model") is True


def test_is_deepseek_configured_from_model(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)

    assert llm_client.is_deepseek_configured("deepseek-v4-flash") is True


def test_parse_json_extracted_features_returns_restricted_model():
    expected_features = make_valid_extracted_features()

    result = llm_client.parse_json_extracted_features(expected_features.model_dump_json())

    assert isinstance(result, ExtractedLeadFeatures)
    assert result == expected_features


def test_parse_json_extracted_features_rejects_invalid_json():
    with pytest.raises(LLMClientError, match="invalid feature JSON"):
        llm_client.parse_json_extracted_features("not json")


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("lead_score", 100),
        ("intent_level", "High"),
        ("disposition", "qualified"),
        ("company_name_present", True),
    ],
)
def test_parse_json_extracted_features_rejects_forbidden_fields(
    field_name,
    field_value,
):
    payload = make_valid_extracted_features().model_dump()
    payload[field_name] = field_value

    with pytest.raises(LLMClientError, match="failed schema validation"):
        llm_client.parse_json_extracted_features(json.dumps(payload))


def test_parse_json_extracted_features_rejects_invalid_customer_kind():
    payload = make_valid_extracted_features().model_dump()
    payload["customer_kind"] = "vip"

    with pytest.raises(LLMClientError, match="failed schema validation"):
        llm_client.parse_json_extracted_features(json.dumps(payload))


def test_call_openai_structured_feature_extraction_returns_features_and_separates_roles(
    monkeypatch,
):
    expected_features = make_valid_extracted_features()
    fake_responses = FakeResponses(response=FakeResponse(expected_features))
    fake_client = FakeClient(responses=fake_responses)

    monkeypatch.setattr(llm_client, "get_openai_client", lambda: fake_client)
    monkeypatch.setattr(llm_client, "get_openai_model", lambda: "test-model")

    result = llm_client.call_openai_structured_feature_extraction(
        system_prompt="feature system prompt",
        user_prompt="untrusted lead JSON",
    )

    assert result == expected_features
    assert fake_responses.kwargs["input"] == [
        {"role": "system", "content": "feature system prompt"},
        {"role": "user", "content": "untrusted lead JSON"},
    ]
    assert fake_responses.kwargs["text_format"] is ExtractedLeadFeatures


def test_call_openai_structured_feature_extraction_wraps_provider_error(monkeypatch):
    fake_responses = FakeResponses(error=RuntimeError("fake OpenAI error"))
    fake_client = FakeClient(responses=fake_responses)

    monkeypatch.setattr(llm_client, "get_openai_client", lambda: fake_client)
    monkeypatch.setattr(llm_client, "get_openai_model", lambda: "test-model")

    with pytest.raises(LLMClientError, match="structured feature extraction failed"):
        llm_client.call_openai_structured_feature_extraction(
            system_prompt="feature system prompt",
            user_prompt="untrusted lead JSON",
        )


def test_call_openai_structured_feature_extraction_rejects_empty_output(monkeypatch):
    fake_responses = FakeResponses(response=FakeResponse(None))
    fake_client = FakeClient(responses=fake_responses)

    monkeypatch.setattr(llm_client, "get_openai_client", lambda: fake_client)
    monkeypatch.setattr(llm_client, "get_openai_model", lambda: "test-model")

    with pytest.raises(LLMClientError, match="empty structured feature output"):
        llm_client.call_openai_structured_feature_extraction(
            system_prompt="feature system prompt",
            user_prompt="untrusted lead JSON",
        )


def test_call_openai_structured_feature_extraction_uses_deepseek_json_mode(monkeypatch):
    expected_features = make_valid_extracted_features()
    fake_completions = FakeChatCompletions(
        response=FakeChatResponse(expected_features.model_dump_json())
    )
    fake_client = FakeDeepSeekClient(completions=fake_completions)

    monkeypatch.setattr(llm_client, "get_openai_client", lambda: fake_client)
    monkeypatch.setattr(llm_client, "get_openai_model", lambda: "deepseek-v4-flash")

    result = llm_client.call_openai_structured_feature_extraction(
        system_prompt="feature system prompt",
        user_prompt="untrusted lead JSON",
    )

    assert result == expected_features
    assert fake_completions.kwargs["messages"][0] == {
        "role": "system",
        "content": "feature system prompt",
    }
    assert fake_completions.kwargs["messages"][1]["role"] == "user"
    assert fake_completions.kwargs["messages"][1]["content"].startswith("untrusted lead JSON")
    assert fake_completions.kwargs["response_format"] == {"type": "json_object"}
    assert "lead_score" not in fake_completions.kwargs["messages"][1]["content"]


def test_call_deepseek_structured_feature_extraction_rejects_empty_output():
    fake_completions = FakeChatCompletions(response=FakeChatResponse(None))
    fake_client = FakeDeepSeekClient(completions=fake_completions)

    with pytest.raises(LLMClientError, match="empty structured feature output"):
        llm_client.call_deepseek_structured_feature_extraction(
            client=fake_client,
            model="deepseek-v4-flash",
            system_prompt="feature system prompt",
            user_prompt="untrusted lead JSON",
        )
