import pytest

from lead_cleaner.schemas.ai_output import LeadAnalysisResult
from lead_cleaner.services import llm_client
from lead_cleaner.services.llm_client import LLMClientError


class FakeResponse:
    def __init__(self, output_parsed):
        self.output_parsed = output_parsed


class FakeResponses:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def parse(self, **kwargs):
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


def make_valid_analysis_result() -> LeadAnalysisResult:
    return LeadAnalysisResult(
        lead_type="B2B",
        lead_subtype="Agency",
        intent_level="High",
        lead_score=88,
        lead_summary="A high-value travel agency lead asking for a China itinerary.",
        recommended_action="Review the lead and prepare a tailored follow-up.",
        followup_email_draft="Thank you for your inquiry. We would be happy to learn more about your group.",
        analysis_method="llm",
        confidence=0.9,
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


def test_call_openai_structured_analysis_wraps_openai_error(monkeypatch):
    fake_responses = FakeResponses(error=RuntimeError("fake OpenAI error"))

    fake_client = FakeClient(responses=fake_responses)

    monkeypatch.setattr(llm_client, "get_openai_client", lambda: fake_client)

    monkeypatch.setattr(llm_client, "get_openai_model", lambda: "test_model")

    with pytest.raises(LLMClientError) as error_info:
        llm_client.call_openai_structured_analysis("test prompt")

    assert "OpenAI structured analysis failed" in str(error_info.value)


def test_call_openai_structured_analysis_raises_error_when_output_parsed_is_none(monkeypatch):
    fake_response = FakeResponse(output_parsed=None)
    fake_responses = FakeResponses(response=fake_response)
    fake_client = FakeClient(responses=fake_responses)

    monkeypatch.setattr(llm_client, "get_openai_client", lambda: fake_client)
    monkeypatch.setattr(llm_client, "get_openai_model", lambda: "test-model")

    with pytest.raises(LLMClientError) as error_info:
        llm_client.call_openai_structured_analysis("test prompt")
    assert "OpenAI returned empty structured output." in str(error_info.value)


def test_call_openai_structured_analysis_returns_parsed_result(monkeypatch):
    expected_result = make_valid_analysis_result()
    fake_response = FakeResponse(output_parsed=expected_result)
    fake_responses = FakeResponses(response=fake_response)
    fake_client = FakeClient(responses=fake_responses)

    monkeypatch.setattr(llm_client, "get_openai_client", lambda: fake_client)
    monkeypatch.setattr(llm_client, "get_openai_model", lambda: "test-model")

    result = llm_client.call_openai_structured_analysis("test prompt")

    assert isinstance(result, LeadAnalysisResult)
    assert result == expected_result
    assert result.lead_type == "B2B"
    assert result.analysis_method == "llm"


def test_is_deepseek_configured_from_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")

    assert llm_client.is_deepseek_configured("some-model") is True


def test_is_deepseek_configured_from_model(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)

    assert llm_client.is_deepseek_configured("deepseek-v4-flash") is True


def test_parse_json_analysis_result_returns_model():
    expected_result = make_valid_analysis_result()

    result = llm_client.parse_json_analysis_result(expected_result.model_dump_json())

    assert result == expected_result


def test_parse_json_analysis_result_rejects_invalid_json():
    with pytest.raises(LLMClientError) as error_info:
        llm_client.parse_json_analysis_result("not json")

    assert "invalid JSON" in str(error_info.value)


def test_call_openai_structured_analysis_uses_deepseek_chat_completions(monkeypatch):
    expected_result = make_valid_analysis_result()
    fake_completions = FakeChatCompletions(
        response=FakeChatResponse(expected_result.model_dump_json())
    )
    fake_client = FakeDeepSeekClient(completions=fake_completions)

    monkeypatch.setattr(llm_client, "get_openai_client", lambda: fake_client)
    monkeypatch.setattr(llm_client, "get_openai_model", lambda: "deepseek-v4-flash")

    result = llm_client.call_openai_structured_analysis("test prompt")

    assert result == expected_result
    assert fake_completions.kwargs["model"] == "deepseek-v4-flash"
    assert fake_completions.kwargs["response_format"] == {"type": "json_object"}
    assert fake_completions.kwargs["messages"][1]["content"].startswith("test prompt")
