from types import SimpleNamespace

import httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from lead_cleaner.config import AppMode, LLMProvider, Settings
from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import LeadFeatures, SecuritySignals
from lead_cleaner.services import openai_recommendation_generator
from lead_cleaner.services.feature_extractor import FeatureExtractionOutcome
from lead_cleaner.services.lead_analyzer import build_policy_analysis
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
from lead_cleaner.services.openai_recommendation_generator import (
    OpenAIRecommendationGenerator,
)
from lead_cleaner.services.recommendation_generator import (
    GroundedRecommendationDraft,
)


class FakeResponse:
    def __init__(
        self,
        output_parsed,
        *,
        status: str = "completed",
        output=None,
        incomplete_reason: str | None = None,
    ) -> None:
        self.output_parsed = output_parsed
        self.status = status
        self.output = output or []
        self.incomplete_details = (
            SimpleNamespace(reason=incomplete_reason) if incomplete_reason else None
        )


class FakeResponses:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return self.response


class FakeOpenAI:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self.responses = FakeResponses(response=response, error=error)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def make_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/responses")


def make_status_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=make_request())


def make_lead(message: str = "We need a private tour quotation for 20 people.") -> CleanedLead:
    return CleanedLead(
        lead_id="lead-1",
        name="Example Lead",
        email="lead@example.com",
        company_name="Example Travel Agency",
        message=message,
        source="Website",
    )


def make_analysis(*, language: str = "en"):
    return build_policy_analysis(
        FeatureExtractionOutcome(
            features=LeadFeatures(
                customer_kind="agency",
                group_size=20,
                asks_for_price=True,
                requests_private_or_custom_service=True,
                language=language,
                company_name_present=True,
                cleaned_message_length=100,
            ),
            execution_mode=AppMode.LIVE,
            analysis_method="rule_features",
        ),
        SecuritySignals(),
    )


def make_chunk(chunk_id: str = "chunk-1") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_type="notion_page",
        notion_page_id="private-page-id",
        source_title="Private Tour",
        source_path="Knowledge/Private Tour",
        doc_type="product",
        region="general",
        product_name="Private Tour",
        section="Suitable For",
        text="Suitable for private groups. Confirm dates before quoting.",
        score=1.0,
        rank=1,
        retrieval_source="fusion",
    )


def make_draft(*, cited_chunk_ids=None) -> GroundedRecommendationDraft:
    return GroundedRecommendationDraft(
        recommended_action="Confirm the travel dates and prepare a tailored quotation.",
        followup_email_draft=(
            "Thank you for your inquiry. Please confirm your preferred travel dates."
        ),
        cited_chunk_ids=cited_chunk_ids or ["chunk-1"],
    )


def make_live_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "app_mode": AppMode.LIVE,
        "allow_network": True,
        "llm_provider": LLMProvider.OPENAI,
        "openai_api_key": "test-key",
        "openai_model": "test-model",
        "grounded_recommendation_enabled": True,
        "recommendation_max_output_tokens": 1024,
    }
    values.update(overrides)
    return Settings(**values)


def test_generate_returns_validated_grounded_draft_and_request() -> None:
    expected = make_draft()
    fake_sdk_client = FakeOpenAI(response=FakeResponse(expected))
    generator = OpenAIRecommendationGenerator(
        client=fake_sdk_client,
        model="test-model",
        max_output_tokens=1024,
    )

    result = generator.generate(
        cleaned_lead=make_lead(),
        analysis_result=make_analysis(),
        chunks=[make_chunk()],
    )

    assert result == expected
    request = fake_sdk_client.responses.kwargs
    assert request["model"] == "test-model"
    assert request["text_format"] is GroundedRecommendationDraft
    assert request["max_output_tokens"] == 1024
    assert request["input"][0]["role"] == "system"
    assert request["input"][1]["role"] == "user"
    assert "chunk-1" in request["input"][1]["content"]


def test_generate_uses_chinese_prompt_for_chinese_lead() -> None:
    fake_sdk_client = FakeOpenAI(response=FakeResponse(make_draft()))
    generator = OpenAIRecommendationGenerator(client=fake_sdk_client, model="test-model")

    generator.generate(
        cleaned_lead=make_lead("我们需要20人的四川私人定制行程和报价。"),
        analysis_result=make_analysis(language="zh"),
        chunks=[make_chunk()],
    )

    system_prompt = fake_sdk_client.responses.kwargs["input"][0]["content"]
    assert "你是一个受严格约束" in system_prompt


def test_generate_rejects_citation_outside_retrieved_whitelist() -> None:
    fake_sdk_client = FakeOpenAI(response=FakeResponse(make_draft(cited_chunk_ids=["chunk-fake"])))
    generator = OpenAIRecommendationGenerator(client=fake_sdk_client, model="test-model")

    with pytest.raises(LLMSchemaValidationError, match="were not retrieved"):
        generator.generate(
            cleaned_lead=make_lead(),
            analysis_result=make_analysis(),
            chunks=[make_chunk()],
        )


def test_generate_requires_retrieved_chunks_without_calling_client() -> None:
    fake_sdk_client = FakeOpenAI(response=FakeResponse(make_draft()))
    generator = OpenAIRecommendationGenerator(client=fake_sdk_client, model="test-model")

    with pytest.raises(LLMSchemaValidationError, match="at least one"):
        generator.generate(
            cleaned_lead=make_lead(),
            analysis_result=make_analysis(),
            chunks=[],
        )

    assert fake_sdk_client.responses.kwargs is None


def test_generate_rejects_incomplete_response() -> None:
    fake_sdk_client = FakeOpenAI(
        response=FakeResponse(
            None,
            status="incomplete",
            incomplete_reason="max_output_tokens",
        )
    )
    generator = OpenAIRecommendationGenerator(client=fake_sdk_client, model="test-model")

    with pytest.raises(LLMResponseIncompleteError, match="max_output_tokens"):
        generator.generate(
            cleaned_lead=make_lead(),
            analysis_result=make_analysis(),
            chunks=[make_chunk()],
        )


def test_generate_rejects_refusal_nested_in_message_content() -> None:
    refusal = SimpleNamespace(
        type="message",
        content=[SimpleNamespace(type="refusal", refusal="Cannot comply")],
    )
    fake_sdk_client = FakeOpenAI(response=FakeResponse(None, output=[refusal]))
    generator = OpenAIRecommendationGenerator(client=fake_sdk_client, model="test-model")

    with pytest.raises(LLMRefusalError):
        generator.generate(
            cleaned_lead=make_lead(),
            analysis_result=make_analysis(),
            chunks=[make_chunk()],
        )


def test_generate_rejects_empty_structured_output() -> None:
    fake_sdk_client = FakeOpenAI(response=FakeResponse(None))
    generator = OpenAIRecommendationGenerator(client=fake_sdk_client, model="test-model")

    with pytest.raises(LLMInvalidJSONError):
        generator.generate(
            cleaned_lead=make_lead(),
            analysis_result=make_analysis(),
            chunks=[make_chunk()],
        )


@pytest.mark.parametrize(
    ("sdk_error", "expected_error"),
    [
        (APITimeoutError(make_request()), LLMTimeoutError),
        (
            RateLimitError("rate limited", response=make_status_response(429), body=None),
            LLMRateLimitError,
        ),
        (APIConnectionError(request=make_request()), LLMProviderUnavailableError),
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
def test_generate_translates_sdk_errors(sdk_error, expected_error) -> None:
    fake_sdk_client = FakeOpenAI(error=sdk_error)
    generator = OpenAIRecommendationGenerator(client=fake_sdk_client, model="test-model")

    with pytest.raises(expected_error):
        generator.generate(
            cleaned_lead=make_lead(),
            analysis_result=make_analysis(),
            chunks=[make_chunk()],
        )


def test_from_settings_uses_reliability_and_token_options(monkeypatch) -> None:
    captured = {}
    fake_sdk_client = FakeOpenAI(response=FakeResponse(make_draft()))

    def fake_openai_constructor(**kwargs):
        captured.update(kwargs)
        return fake_sdk_client

    monkeypatch.setattr(
        openai_recommendation_generator,
        "OpenAI",
        fake_openai_constructor,
    )

    generator = OpenAIRecommendationGenerator.from_settings(
        make_live_settings(
            openai_base_url="https://example.test/v1",
            llm_timeout_seconds=12.5,
            llm_max_retries=2,
            recommendation_max_output_tokens=1200,
        )
    )

    assert captured == {
        "api_key": "test-key",
        "base_url": "https://example.test/v1",
        "timeout": 12.5,
        "max_retries": 2,
    }
    assert generator.max_output_tokens == 1200


def test_disabled_settings_do_not_construct_openai_client(monkeypatch) -> None:
    def fail_if_called(**kwargs):
        raise AssertionError("OpenAI constructor must not be called")

    monkeypatch.setattr(
        openai_recommendation_generator,
        "OpenAI",
        fail_if_called,
    )
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        allow_network=True,
        openai_api_key="test-key",
        openai_model="test-model",
        grounded_recommendation_enabled=False,
    )

    with pytest.raises(LLMConfigurationError, match="ENABLED=true"):
        OpenAIRecommendationGenerator.from_settings(settings)


@pytest.mark.parametrize("max_output_tokens", [255, 2049])
def test_constructor_rejects_unsafe_token_bounds(max_output_tokens: int) -> None:
    with pytest.raises(LLMConfigurationError, match="between 256 and 2048"):
        OpenAIRecommendationGenerator(
            client=FakeOpenAI(),
            model="test-model",
            max_output_tokens=max_output_tokens,
        )


def test_close_closes_underlying_sdk_client() -> None:
    fake_sdk_client = FakeOpenAI(response=FakeResponse(make_draft()))
    generator = OpenAIRecommendationGenerator(client=fake_sdk_client, model="test-model")

    generator.close()

    assert fake_sdk_client.closed is True
