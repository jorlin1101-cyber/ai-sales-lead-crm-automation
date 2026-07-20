import pytest
from pydantic import ValidationError

from lead_cleaner.schemas.ai_output import LeadAnalysisResult
from lead_cleaner.schemas.lead import (
    CleanedLead,
    LeadProcessingResult,
    LeadScoreResult,
    LeadValidationResult,
    RawLeadInput,
)


def make_valid_analysis_result() -> LeadAnalysisResult:
    return LeadAnalysisResult(
        lead_type="B2B",
        lead_subtype="Agency",
        intent_level="High",
        lead_score=85,
        lead_summary="A high-value agency lead asking for a China tour quotation.",
        recommended_action="Review the lead and prepare a tailored follow-up.",
        followup_email_draft="Thank you for your inquiry. We would be happy to learn more about your group.",
        analysis_method="llm",
        confidence=0.9,
    )


def test_raw_lead_input_valid_data():
    lead = RawLeadInput(
        name="Elena",
        email="elena@example.com",
        company_name="Example Inc.",
        message="I am interested in your product.",
        source="Website",
    )

    assert lead.name == "Elena"
    assert lead.email == "elena@example.com"
    assert lead.company_name == "Example Inc."
    assert lead.message == "I am interested in your product."
    assert lead.source == "Website"


def test_raw_lead_input_default_source():
    lead = RawLeadInput(
        name="Elena",
        email="elena@example.com",
        company_name="Example Inc.",
        message="I am interested in your product.",
    )

    assert lead.source == "Unknown"


def test_raw_lead_input_missing_email():
    with pytest.raises(ValidationError):
        RawLeadInput(
            name="Elena",
            company_name="Example Inc.",
            message="I am interested in your product.",
            source="Website",
        )


def test_raw_lead_input_empty_message():
    with pytest.raises(ValidationError):
        RawLeadInput(
            name="Elena",
            email="elena@example.com",
            company_name="Example Inc.",
            message="",
            source="Website",
        )


def test_raw_lead_input_preserves_external_lead_id():
    lead = RawLeadInput(
        external_lead_id="website-form-001",
        email="john@example.com",
        message="I need a private tour.",
    )

    assert lead.external_lead_id == "website-form-001"


def test_raw_lead_input_rejects_unknown_company_field():
    payload = {
        "email": "john@example.com",
        "message": "I need a private tour.",
        "company": "ABC Travel",
    }

    with pytest.raises(ValidationError) as exc_info:
        RawLeadInput.model_validate(payload)

    errors = exc_info.value.errors()

    assert any(
        error["type"] == "extra_forbidden" and error["loc"] == ("company",) for error in errors
    )


def test_raw_lead_input_rejects_message_over_max_length():
    with pytest.raises(ValidationError):
        RawLeadInput(
            email="john@example.com",
            message="x" * 5001,
        )


def test_cleaned_lead_valid_data():
    lead = CleanedLead(
        lead_id="12345",
        name="Elena",
        email="elena@example.com",
        company_name="Example Inc.",
        message="I am interested in your product.",
        source="Website",
    )

    assert lead.lead_id == "12345"
    assert lead.name == "Elena"
    assert lead.email == "elena@example.com"
    assert lead.company_name == "Example Inc."
    assert lead.message == "I am interested in your product."
    assert lead.source == "Website"


def test_cleaned_lead_missing_lead_id():
    with pytest.raises(ValidationError):
        CleanedLead(
            name="Elena",
            email="elena@example.com",
            company_name="Example Inc.",
            message="I am interested in your product.",
            source="Website",
        )


def test_lead_validation_result_valid_data():
    result = LeadValidationResult(
        is_valid=True,
    )

    assert result.is_valid is True
    assert result.error_codes == []


def test_lead_validation_result_invalid_requires_error_code():
    with pytest.raises(ValidationError):
        LeadValidationResult(
            is_valid=False,
        )


def test_lead_validation_result_rejects_unknown_error_code():
    payload = {
        "is_valid": False,
        "error_codes": ["some_invalid_reason"],
    }

    with pytest.raises(ValidationError):
        LeadValidationResult.model_validate(payload)


def test_lead_validation_result_accepts_empty_email_error():
    result = LeadValidationResult(
        is_valid=False,
        error_codes=["empty_email"],
    )

    assert result.is_valid is False
    assert result.error_codes == ["empty_email"]


def test_lead_validation_result_valid_cannot_have_error_codes():
    with pytest.raises(ValidationError):
        LeadValidationResult(
            is_valid=True,
            error_codes=["empty_email"],
        )


def test_lead_score_result_valid_data():
    result = LeadScoreResult(
        lead_type="B2B",
        lead_subtype="School",
        intent_level="High",
        lead_score=85,
    )

    assert result.lead_type == "B2B"
    assert result.lead_subtype == "School"
    assert result.intent_level == "High"
    assert result.lead_score == 85


def test_lead_score_result_invalid_lead_score():
    with pytest.raises(ValidationError):
        LeadScoreResult(
            lead_type="B2B",
            lead_subtype="School",
            intent_level="High",
            lead_score=150,
        )


def test_lead_score_result_invalid_lead_type():
    with pytest.raises(ValidationError):
        LeadScoreResult(
            lead_type="InvalidType",
            lead_subtype="School",
            intent_level="High",
            lead_score=85,
        )


def test_lead_score_result_invalid_lead_subtype():
    with pytest.raises(ValidationError):
        LeadScoreResult(
            lead_type="B2B",
            lead_subtype="InvalidSubtype",
            intent_level="High",
            lead_score=85,
        )


def test_lead_score_result_invalid_intent_level():
    with pytest.raises(ValidationError):
        LeadScoreResult(
            lead_type="B2B",
            lead_subtype="School",
            intent_level="InvalidIntentLevel",
            lead_score=85,
        )


def test_lead_score_result_valid_b2c_large_group():
    result = LeadScoreResult(
        lead_type="B2C",
        lead_subtype="LargeGroup",
        intent_level="High",
        lead_score=88,
    )

    assert result.lead_type == "B2C"
    assert result.lead_subtype == "LargeGroup"
    assert result.intent_level == "High"
    assert result.lead_score == 88


def test_lead_score_result_invalid_b2c_subtype():
    with pytest.raises(ValidationError):
        LeadScoreResult(
            lead_type="B2C",
            lead_subtype="RandomSubtype",
            intent_level="High",
            lead_score=80,
        )


def test_lead_analysis_result_valid_data():
    result = make_valid_analysis_result()

    assert result.lead_type == "B2B"
    assert result.lead_subtype == "Agency"
    assert result.intent_level == "High"
    assert result.lead_score == 85
    assert result.analysis_method == "llm"
    assert result.confidence == 0.9


def test_lead_analysis_result_invalid_analysis_method():
    with pytest.raises(ValidationError):
        LeadAnalysisResult(
            lead_type="B2B",
            lead_subtype="Agency",
            intent_level="High",
            lead_score=85,
            lead_summary="A valid summary.",
            recommended_action="Review manually.",
            followup_email_draft="Thank you for your inquiry.",
            analysis_method="invalid_method",
            confidence=0.9,
        )


def test_lead_analysis_result_invalid_confidence():
    with pytest.raises(ValidationError):
        LeadAnalysisResult(
            lead_type="B2B",
            lead_subtype="Agency",
            intent_level="High",
            lead_score=85,
            lead_summary="A valid summary.",
            recommended_action="Review manually.",
            followup_email_draft="Thank you for your inquiry.",
            analysis_method="llm",
            confidence=1.5,
        )


def test_lead_processing_result_with_analysis_result():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="John Doe",
        email="john@example.com",
        company_name="Spain Travel Agency",
        message="We want a quotation for a China tour.",
        source="Website",
    )

    validation_result = LeadValidationResult(
        is_valid=True,
    )

    analysis_result = make_valid_analysis_result()

    result = LeadProcessingResult(
        cleaned_lead=cleaned_lead,
        validation_result=validation_result,
        analysis_result=analysis_result,
    )

    assert result.cleaned_lead.email == "john@example.com"
    assert result.validation_result.is_valid is True
    assert result.analysis_result is not None
    assert result.analysis_result.lead_subtype == "Agency"
    assert result.analysis_result.analysis_method == "llm"
    assert result.sources == []


def test_lead_processing_result_without_analysis_result():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="John Doe",
        email="invalid-email",
        company_name="",
        message="I am interested.",
        source="Website",
    )

    validation_result = LeadValidationResult(
        is_valid=False,
        error_codes=["invalid_email_format"],
    )

    result = LeadProcessingResult(
        cleaned_lead=cleaned_lead,
        validation_result=validation_result,
    )

    assert result.validation_result.is_valid is False
    assert result.analysis_result is None
    assert result.sources == []
