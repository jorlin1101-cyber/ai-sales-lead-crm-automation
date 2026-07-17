import pytest

from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.ai_output import LeadAnalysisResult
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


def test_analyze_lead_with_llm_returns_analysis_result(monkeypatch):
    cleaned_lead = make_cleaned_lead()
    expected_prompt = "test prompt"
    expected_result = make_valid_analysis_result()

    monkeypatch.setattr(
        ai_analysis, "build_lead_analysis_prompt", lambda cleaned_lead: expected_prompt
    )
    monkeypatch.setattr(
        ai_analysis, "call_openai_structured_analysis", lambda prompt: expected_result
    )

    result = ai_analysis.analyze_lead_with_llm(cleaned_lead)

    assert isinstance(result, LeadAnalysisResult)
    assert result == expected_result
    assert result.lead_type == "B2B"
    assert result.analysis_method == "llm"


def test_analyze_lead_with_llm_passes_cleaned_lead_and_prompt(monkeypatch):
    cleaned_lead = make_cleaned_lead()
    expected_prompt = "test prompt"
    expected_result = make_valid_analysis_result()
    captured = {}

    def fake_build_lead_analysis_prompt(cleaned_lead_arg):
        captured["cleaned_lead"] = cleaned_lead_arg
        return expected_prompt

    def fake_call_openai_structured_analysis(prompt_arg):
        captured["prompt"] = prompt_arg
        return expected_result

    monkeypatch.setattr(ai_analysis, "build_lead_analysis_prompt", fake_build_lead_analysis_prompt)
    monkeypatch.setattr(
        ai_analysis, "call_openai_structured_analysis", fake_call_openai_structured_analysis
    )

    result = ai_analysis.analyze_lead_with_llm(cleaned_lead)

    assert result == expected_result
    assert captured["cleaned_lead"] == cleaned_lead
    assert captured["prompt"] == expected_prompt


def test_analyze_lead_with_llm_propagates_llm_client_error(monkeypatch):
    cleaned_lead = make_cleaned_lead()
    expected_prompt = "test prompt"
    captured = {}

    def fake_build_lead_analysis_prompt(cleaned_lead_arg):
        captured["cleaned_lead"] = cleaned_lead_arg
        return expected_prompt

    def fake_call_openai_structured_analysis(prompt_arg):
        captured["prompt"] = prompt_arg
        raise LLMClientError("fake LLM failure")

    monkeypatch.setattr(ai_analysis, "build_lead_analysis_prompt", fake_build_lead_analysis_prompt)
    monkeypatch.setattr(
        ai_analysis, "call_openai_structured_analysis", fake_call_openai_structured_analysis
    )

    with pytest.raises(LLMClientError) as error_info:
        ai_analysis.analyze_lead_with_llm(cleaned_lead)

    assert "fake LLM failure" in str(error_info.value)
    assert captured["cleaned_lead"] == cleaned_lead
    assert captured["prompt"] == expected_prompt
