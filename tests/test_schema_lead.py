import pytest
from pydantic import ValidationError

from lead_cleaner.schemas.ai_output import AnalysisMetadata, LeadAnalysisResult
from lead_cleaner.schemas.lead import (
    CleanedLead,
    LeadProcessingResult,
    LeadValidationResult,
    RawLeadInput,
)
from lead_cleaner.schemas.policy import (
    LeadDecision,
    LeadFeatures,
    ScoreComponent,
    SecuritySignals,
)


def make_valid_analysis_result() -> LeadAnalysisResult:
    return LeadAnalysisResult(
        features=LeadFeatures(
            customer_kind="agency",
            asks_for_price=True,
            company_name_present=True,
            cleaned_message_length=60,
        ),
        security_signals=SecuritySignals(),
        decision=LeadDecision(
            lead_type="B2B",
            lead_subtype="Agency",
            disposition="qualified",
            intent_level="High",
            lead_score=85,
            score_breakdown=[
                ScoreComponent(
                    component="customer_fit",
                    points=30,
                    max_points=30,
                    reason_codes=["agency_customer"],
                ),
                ScoreComponent(
                    component="intent_strength",
                    points=22,
                    max_points=30,
                    reason_codes=["two_intent_signals"],
                ),
                ScoreComponent(
                    component="order_value_proxy",
                    points=18,
                    max_points=25,
                    reason_codes=["private_or_custom_service"],
                ),
                ScoreComponent(
                    component="information_completeness",
                    points=15,
                    max_points=15,
                    reason_codes=["complete_information"],
                ),
            ],
            needs_review=False,
            review_reasons=[],
            policy_version="policy-v1",
        ),
        lead_summary="A high-value agency lead asking for a China tour quotation.",
        recommended_action="Review the lead and prepare a tailored follow-up.",
        followup_email_draft="Thank you for your inquiry. We would be happy to learn more about your group.",
        metadata=AnalysisMetadata(
            analysis_method="llm_features",
            recommendation_method="generic_template",
            retrieval_method="skipped",
            prompt_version="lead-features-v1",
        ),
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


def test_lead_analysis_result_valid_data():
    result = make_valid_analysis_result()

    assert result.features.customer_kind == "agency"
    assert result.decision.lead_type == "B2B"
    assert result.decision.lead_subtype == "Agency"
    assert result.decision.intent_level == "High"
    assert result.decision.lead_score == 85
    assert result.metadata.analysis_method == "llm_features"


def test_lead_analysis_result_invalid_analysis_method():
    payload = make_valid_analysis_result().model_dump()
    payload["metadata"]["analysis_method"] = "invalid_method"

    with pytest.raises(ValidationError):
        LeadAnalysisResult.model_validate(payload)


def test_lead_analysis_result_rejects_removed_confidence_field():
    payload = make_valid_analysis_result().model_dump()
    payload["confidence"] = 1.0

    with pytest.raises(ValidationError, match="extra_forbidden"):
        LeadAnalysisResult.model_validate(payload)


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
    assert result.analysis_result.decision.lead_subtype == "Agency"
    assert result.analysis_result.metadata.analysis_method == "llm_features"
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
