import pytest
from pydantic import ValidationError
from lead_cleaner.schemas.ai_output import LeadAnalysisResult

def test_ai_output_valid_llm_output():
    result = LeadAnalysisResult(
        lead_type="B2B",
        lead_subtype="Agency",
        intent_level="High",
        lead_score=90,
        lead_summary="A travel agency is asking for a China tour quotation.",
        recommended_action="Review the lead immediately and prepare a tailored follow-up.",
        followup_email_draft="Hi John, thank you for your inquiry. We would be happy to help.",
        analysis_method="llm",
        confidence=0.9,
    )
    lead_type="B2B",
    lead_subtype="Agency",
    intent_level="High",
    lead_score=90,
    lead_summary="A travel agency is asking for a China tour quotation.",
    recommended_action="Review the lead immediately and prepare a tailored follow-up.",
    followup_email_draft="Hi John, thank you for your inquiry. We would be happy to help.",
    analysis_method="llm",
    confidence=0.9,


def test_lead_analysis_result_valid_rule_fallback_output():
    result = LeadAnalysisResult(
        lead_type="B2C",
        lead_subtype="LargeGroup",
        intent_level="High",
        lead_score=85,
        lead_summary="Rule-based fallback identified this as a high-value large group lead.",
        recommended_action="Review manually before sending a follow-up.",
        followup_email_draft="",
        analysis_method="rule_fallback",
        confidence=0.4,
    )

    assert result.lead_type == "B2C"
    assert result.lead_subtype == "LargeGroup"
    assert result.analysis_method == "rule_fallback"
    assert result.followup_email_draft == ""


def test_lead_analysis_result_invalid_lead_type():
    with pytest.raises(ValidationError):
        LeadAnalysisResult(
            lead_type="InvalidType",
            lead_subtype="Agency",
            intent_level="High",
            lead_score=90,
            lead_summary="A travel agency is asking for a China tour quotation.",
            recommended_action="Review immediately.",
            followup_email_draft="Hi John, thank you for your inquiry.",
            analysis_method="llm",
            confidence=0.9,
        )


def test_lead_analysis_result_invalid_lead_subtype():
    with pytest.raises(ValidationError):
        LeadAnalysisResult(
            lead_type="B2B",
            lead_subtype="RandomSubtype",
            intent_level="High",
            lead_score=90,
            lead_summary="A travel agency is asking for a China tour quotation.",
            recommended_action="Review immediately.",
            followup_email_draft="Hi John, thank you for your inquiry.",
            analysis_method="llm",
            confidence=0.9,
        )


def test_lead_analysis_result_invalid_intent_level():
    with pytest.raises(ValidationError):
        LeadAnalysisResult(
            lead_type="B2B",
            lead_subtype="Agency",
            intent_level="VeryHigh",
            lead_score=90,
            lead_summary="A travel agency is asking for a China tour quotation.",
            recommended_action="Review immediately.",
            followup_email_draft="Hi John, thank you for your inquiry.",
            analysis_method="llm",
            confidence=0.9,
        )


def test_lead_analysis_result_invalid_score_range():
    with pytest.raises(ValidationError):
        LeadAnalysisResult(
            lead_type="B2B",
            lead_subtype="Agency",
            intent_level="High",
            lead_score=150,
            lead_summary="A travel agency is asking for a China tour quotation.",
            recommended_action="Review immediately.",
            followup_email_draft="Hi John, thank you for your inquiry.",
            analysis_method="llm",
            confidence=0.9,
        )


def test_lead_analysis_result_empty_summary():
    with pytest.raises(ValidationError):
        LeadAnalysisResult(
            lead_type="B2B",
            lead_subtype="Agency",
            intent_level="High",
            lead_score=90,
            lead_summary="",
            recommended_action="Review immediately.",
            followup_email_draft="Hi John, thank you for your inquiry.",
            analysis_method="llm",
            confidence=0.9,
        )


def test_lead_analysis_result_empty_recommended_action():
    with pytest.raises(ValidationError):
        LeadAnalysisResult(
            lead_type="B2B",
            lead_subtype="Agency",
            intent_level="High",
            lead_score=90,
            lead_summary="A travel agency is asking for a China tour quotation.",
            recommended_action="",
            followup_email_draft="Hi John, thank you for your inquiry.",
            analysis_method="llm",
            confidence=0.9,
        )


def test_lead_analysis_result_invalid_analysis_method():
    with pytest.raises(ValidationError):
        LeadAnalysisResult(
            lead_type="B2B",
            lead_subtype="Agency",
            intent_level="High",
            lead_score=90,
            lead_summary="A travel agency is asking for a China tour quotation.",
            recommended_action="Review immediately.",
            followup_email_draft="Hi John, thank you for your inquiry.",
            analysis_method="manual",
            confidence=0.9,
        )


def test_lead_analysis_result_invalid_confidence_range():
    with pytest.raises(ValidationError):
        LeadAnalysisResult(
            lead_type="B2B",
            lead_subtype="Agency",
            intent_level="High",
            lead_score=90,
            lead_summary="A travel agency is asking for a China tour quotation.",
            recommended_action="Review immediately.",
            followup_email_draft="Hi John, thank you for your inquiry.",
            analysis_method="llm",
            confidence=1.5,
        )
