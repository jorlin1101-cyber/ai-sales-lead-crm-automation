import pytest

from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import ExtractedLeadFeatures
from lead_cleaner.services import ai_analysis
from lead_cleaner.services.llm_client import LLMClientError


def make_cleaned_lead() -> CleanedLead:
    return CleanedLead(
        lead_id="lead-123",
        name="John Smith",
        email="john@example.com",
        company_name="Global Travel Agency",
        message="We are interested in planning a private China itinerary for 20 clients.",
        source="Website",
    )


def make_valid_extracted_features() -> ExtractedLeadFeatures:
    return ExtractedLeadFeatures(
        customer_kind="agency",
        group_size=20,
        mentions_specific_dates=True,
        asks_for_price=True,
        requests_private_or_custom_service=True,
        destinations=["China"],
        language="en",
    )


def test_extract_lead_features_with_llm_returns_restricted_features(monkeypatch):
    cleaned_lead = make_cleaned_lead()
    expected_features = make_valid_extracted_features()

    monkeypatch.setattr(
        ai_analysis,
        "get_lead_feature_system_prompt",
        lambda language: "feature system prompt",
    )
    monkeypatch.setattr(
        ai_analysis,
        "build_lead_feature_prompt",
        lambda cleaned_lead, language: "untrusted lead JSON",
    )
    monkeypatch.setattr(
        ai_analysis,
        "call_openai_structured_feature_extraction",
        lambda system_prompt, user_prompt: expected_features,
    )

    result = ai_analysis.extract_lead_features_with_llm(cleaned_lead)

    assert isinstance(result, ExtractedLeadFeatures)
    assert result == expected_features


def test_extract_lead_features_with_llm_passes_prompts_and_language(monkeypatch):
    cleaned_lead = make_cleaned_lead()
    expected_features = make_valid_extracted_features()
    captured = {}

    def fake_get_system_prompt(language):
        captured["system_language"] = language
        return "Chinese feature system prompt"

    def fake_build_user_prompt(cleaned_lead_arg, language):
        captured["cleaned_lead"] = cleaned_lead_arg
        captured["user_language"] = language
        return "Chinese untrusted lead JSON"

    def fake_call_feature_extraction(system_prompt, user_prompt):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return expected_features

    monkeypatch.setattr(
        ai_analysis,
        "get_lead_feature_system_prompt",
        fake_get_system_prompt,
    )
    monkeypatch.setattr(
        ai_analysis,
        "build_lead_feature_prompt",
        fake_build_user_prompt,
    )
    monkeypatch.setattr(
        ai_analysis,
        "call_openai_structured_feature_extraction",
        fake_call_feature_extraction,
    )

    result = ai_analysis.extract_lead_features_with_llm(
        cleaned_lead,
        language="zh",
    )

    assert result == expected_features
    assert captured == {
        "system_language": "zh",
        "cleaned_lead": cleaned_lead,
        "user_language": "zh",
        "system_prompt": "Chinese feature system prompt",
        "user_prompt": "Chinese untrusted lead JSON",
    }


def test_extract_lead_features_with_llm_propagates_llm_client_error(monkeypatch):
    cleaned_lead = make_cleaned_lead()

    monkeypatch.setattr(
        ai_analysis,
        "get_lead_feature_system_prompt",
        lambda language: "feature system prompt",
    )
    monkeypatch.setattr(
        ai_analysis,
        "build_lead_feature_prompt",
        lambda cleaned_lead, language: "untrusted lead JSON",
    )

    def fake_call_feature_extraction(system_prompt, user_prompt):
        raise LLMClientError("fake feature extraction failure")

    monkeypatch.setattr(
        ai_analysis,
        "call_openai_structured_feature_extraction",
        fake_call_feature_extraction,
    )

    with pytest.raises(LLMClientError, match="fake feature extraction failure"):
        ai_analysis.extract_lead_features_with_llm(cleaned_lead)
