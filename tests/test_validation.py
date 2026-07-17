from lead_cleaner.services.validation import validate_lead
from lead_cleaner.schemas.lead import CleanedLead


def test_validate_lead_empty_email():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="John Doe",
        email="",
        company_name="Example Corp",
        message="I'm interested in your product.",
        source="Website",
    )
    validation_result = validate_lead(cleaned_lead)
    assert validation_result.is_valid is False
    assert validation_result.error_reason == "empty_email"


def test_validate_lead_invalid_email_format():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="John Doe",
        email="invalid-email-format",
        company_name="Example Corp",
        message="I'm interested in your product.",
        source="Website",
    )
    validation_result = validate_lead(cleaned_lead)
    assert validation_result.is_valid is False
    assert validation_result.error_reason == "invalid_email_format"


def test_validate_lead_empty_message():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="John Doe",
        email="john.doe@example.com",
        company_name="Example Corp",
        message="",
        source="Website",
    )
    validation_result = validate_lead(cleaned_lead)
    assert validation_result.is_valid is False
    assert validation_result.error_reason == "empty_message"


def test_validate_lead_valid_lead():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="John Doe",
        email="john.doe@example.com",
        company_name="Example Corp",
        message="I'm interested in your product.",
        source="Website",
    )
    validation_result = validate_lead(cleaned_lead)
    assert validation_result.is_valid is True
    assert validation_result.error_reason == "valid"
