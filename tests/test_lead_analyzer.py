from lead_cleaner.services import lead_analyzer
from lead_cleaner.schemas.lead import CleanedLead, LeadScoreResult
from lead_cleaner.schemas.ai_output import LeadAnalysisResult
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


def make_score_result() -> LeadScoreResult:
    return LeadScoreResult(
        lead_type="B2B",
        lead_subtype="Agency",
        intent_level="High",
        lead_score=88,
    )


def make_valid_llm_analysis_result() -> LeadAnalysisResult:
    return LeadAnalysisResult(
        lead_type="B2B",
        lead_subtype="Agency",
        intent_level="High",
        lead_score=92,
        lead_summary="LLM analysis result for a high-value agency lead.",
        recommended_action="Prepare a tailored follow-up for human review.",
        followup_email_draft="Thank you for your inquiry. We would be happy to discuss your China itinerary.",
        analysis_method="llm",
        confidence=0.9,
    )


def make_valid_rule_fallback_analysis_result() -> LeadAnalysisResult:
    return LeadAnalysisResult(
        lead_type="B2B",
        lead_subtype="Agency",
        intent_level="High",
        lead_score=88,
        lead_summary=(
            "Rule-based fallback analysis generated from cleaned lead data "
            "because LLM analysis was unavailable."
        ),
        recommended_action="Review this lead manually before taking follow-up action.",
        followup_email_draft="",
        analysis_method="rule_fallback",
        confidence=0.55,
    )


def test_build_rule_fallback_analysis_returns_valid_lead_analysis_result(monkeypatch):
    cleaned_lead = make_cleaned_lead()
    fake_score_result = make_score_result()
    captured = {}

    def fake_score_lead(cleaned_lead_arg):
        captured["cleaned_lead"] = cleaned_lead_arg
        return fake_score_result

    monkeypatch.setattr(
        lead_analyzer,
        "score_lead",
        fake_score_lead,
    )

    result = lead_analyzer.build_rule_fallback_analysis(cleaned_lead)

    assert isinstance(result, LeadAnalysisResult)
    assert result.lead_type == fake_score_result.lead_type
    assert result.lead_subtype == fake_score_result.lead_subtype
    assert result.intent_level == fake_score_result.intent_level
    assert result.lead_score == fake_score_result.lead_score
    assert result.analysis_method == "rule_fallback"
    assert result.lead_summary != ""
    assert result.recommended_action != ""
    assert result.followup_email_draft == ""
    assert 0 <= result.confidence <= 1
    assert captured["cleaned_lead"] == cleaned_lead


def test_analyze_lead_returns_llm_lead_analysis_result(monkeypatch):
    cleaned_lead = make_cleaned_lead()
    expected_llm_result = make_valid_llm_analysis_result()
    captured = {}

    def fake_analyze_lead_with_llm(cleaned_lead_arg):
        captured["cleaned_lead"] = cleaned_lead_arg
        return expected_llm_result

    def fake_rule_fallback_analysis(cleaned_lead_arg):
        raise AssertionError("Fallback should not be called when LLM succeeds.")

    monkeypatch.setattr(lead_analyzer, "analyze_lead_with_llm", fake_analyze_lead_with_llm)
    monkeypatch.setattr(lead_analyzer, "build_rule_fallback_analysis", fake_rule_fallback_analysis)

    result = lead_analyzer.analyze_lead(cleaned_lead)

    assert result == expected_llm_result
    assert result.analysis_method == "llm"
    assert captured["cleaned_lead"] == cleaned_lead


def test_analyze_lead_returns_rule_fallback_analysis_result(monkeypatch):
    cleaned_lead = make_cleaned_lead()
    expected_fallback_result = make_valid_rule_fallback_analysis_result()
    captured = {}

    def fake_analyze_lead_with_llm(cleaned_lead_arg):
        captured["llm_cleaned_lead"] = cleaned_lead_arg
        raise LLMClientError

    def fake_build_rule_fallback_analysis(cleaned_lead_arg):
        captured["fallback_cleaned_lead"] = cleaned_lead_arg
        return expected_fallback_result

    monkeypatch.setattr(lead_analyzer, "analyze_lead_with_llm", fake_analyze_lead_with_llm)
    monkeypatch.setattr(
        lead_analyzer, "build_rule_fallback_analysis", fake_build_rule_fallback_analysis
    )

    result = lead_analyzer.analyze_lead(cleaned_lead)

    assert result == expected_fallback_result
    assert result.analysis_method == "rule_fallback"
    assert captured["llm_cleaned_lead"] == cleaned_lead
    assert captured["fallback_cleaned_lead"] == cleaned_lead
