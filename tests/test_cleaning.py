from lead_cleaner.services.cleaning import clean_lead
from lead_cleaner.schemas.lead import RawLeadInput


def test_clean_lead_normalizes_email():
    raw_lead = RawLeadInput(
        name="John Doe",
        email=" JOHN.DOE@EXAMPLE.COM ",
        company_name="Example Corp",
        message="I'm interested in your product.",
        source="Website",
    )
    cleaned_lead = clean_lead(raw_lead)
    assert cleaned_lead.email == "john.doe@example.com"


def test_clean_lead_strips_name_and_company_name():
    raw_lead = RawLeadInput(
        name=" John Doe  ",
        email="john.doe@example.com",
        company_name=" Example Corp ",
        message="I'm interested in your product.",
        source="Website",
    )
    cleaned_lead = clean_lead(raw_lead)
    assert cleaned_lead.name == "John Doe"
    assert cleaned_lead.company_name == "Example Corp"


def test_clean_lead_converts_none_name_and_company_to_empty_string():
    raw_lead = RawLeadInput(
        name=None,
        email="john.doe@example.com",
        company_name=None,
        message="I'm interested in your product.",
        source="Website",
    )
    cleaned_lead = clean_lead(raw_lead)
    assert cleaned_lead.name == ""
    assert cleaned_lead.company_name == ""


def test_clean_lead_converts_empty_source_to_unknown():
    raw_lead = RawLeadInput(
        name="John Doe",
        email="john.doe@example.com",
        company_name="Example Corp",
        message="I'm interested in your product.",
        source="",
    )
    cleaned_lead = clean_lead(raw_lead)
    assert cleaned_lead.source == "Unknown"


def test_clean_lead_generates_lead_id():
    raw_lead = RawLeadInput(
        name="John Doe",
        email="john.doe@example.com",
        company_name="Example Corp",
        message="I'm interested in your product.",
        source="Website",
    )

    cleaned_lead = clean_lead(raw_lead)

    assert cleaned_lead.lead_id
    assert isinstance(cleaned_lead.lead_id, str)
