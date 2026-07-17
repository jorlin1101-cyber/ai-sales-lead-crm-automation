from lead_cleaner.schemas.lead import RawLeadInput
from lead_cleaner.services.processor import process_lead


def test_process_lead_valid_lead_returns_score_result():
    raw_lead = RawLeadInput(
        name="John Doe",
        email="john@example.com",
        company_name="Spain Travel Agency",
        message=(
            "We want a quotation for a 20 people private tour "
            "to China in September."
        ),
        source="Website",
    )

    result = process_lead(raw_lead)

    assert result.cleaned_lead.email == "john@example.com"
    assert result.validation_result.is_valid is True
    assert result.validation_result.error_reason == "valid"
    assert result.analysis_result is not None
    assert result.analysis_result.lead_type == "B2B"
    assert result.analysis_result.lead_subtype == "Agency"
    assert result.analysis_result.intent_level == "High"


def test_process_lead_invalid_lead_skips_scoring():
    raw_lead = RawLeadInput(
        name="John Doe",
        email="invalid-email",
        company_name="Example Corp",
        message="I am interested in your product.",
        source="Website",
    )

    result = process_lead(raw_lead)

    assert result.cleaned_lead.email == "invalid-email"
    assert result.validation_result.is_valid is False
    assert result.validation_result.error_reason == "invalid_email_format"
    assert result.analysis_result is None
