from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.services.prompt_builder import (
    PROMPT_VERSION,
    build_lead_analysis_prompt,
)


def test_build_lead_analysis_prompt_contains_lead_fields():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="John Doe",
        email="john@example.com",
        company_name="Spain Travel Agency",
        message="We want a quotation for a 20 people private tour to China in September.",
        source="Website",
    )

    prompt = build_lead_analysis_prompt(cleaned_lead)

    assert "John Doe" in prompt
    assert "john@example.com" in prompt
    assert "Spain Travel Agency" in prompt
    assert "20 people private tour" in prompt
    assert "Website" in prompt


def test_build_lead_analysis_prompt_contains_prompt_version():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="John Doe",
        email="john@example.com",
        company_name="Spain Travel Agency",
        message="We want a quotation.",
        source="Website",
    )

    prompt = build_lead_analysis_prompt(cleaned_lead)

    assert PROMPT_VERSION in prompt


def test_build_lead_analysis_prompt_contains_allowed_enum_values():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="John Doe",
        email="john@example.com",
        company_name="Spain Travel Agency",
        message="We want a quotation.",
        source="Website",
    )

    prompt = build_lead_analysis_prompt(cleaned_lead)

    assert "B2B" in prompt
    assert "B2C" in prompt
    assert "Agency" in prompt
    assert "LargeGroup" in prompt
    assert "PrivateCustom" in prompt
    assert "LuxuryHighBudget" in prompt
    assert "High" in prompt
    assert "Medium" in prompt
    assert "Low" in prompt


def test_build_lead_analysis_prompt_contains_b2c_value_rule():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="George Harris",
        email="george@example.com",
        company_name="",
        message="I want to travel with my family.",
        source="Website",
    )

    prompt = build_lead_analysis_prompt(cleaned_lead)

    assert "Do not automatically treat B2C leads as low value" in prompt
    assert "private custom tours" in prompt
    assert "luxury travelers" in prompt


def test_build_lead_analysis_prompt_contains_no_hallucination_rules():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="John Doe",
        email="john@example.com",
        company_name="Spain Travel Agency",
        message="We want a quotation.",
        source="Website",
    )

    prompt = build_lead_analysis_prompt(cleaned_lead)

    assert "Do not invent" in prompt
    assert "budget" in prompt
    assert "travel dates" in prompt
    assert "group size" in prompt
    assert "booking status" in prompt


def test_build_lead_analysis_prompt_contains_output_fields():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="John Doe",
        email="john@example.com",
        company_name="Spain Travel Agency",
        message="We want a quotation.",
        source="Website",
    )

    prompt = build_lead_analysis_prompt(cleaned_lead)

    assert "lead_type" in prompt
    assert "lead_subtype" in prompt
    assert "intent_level" in prompt
    assert "lead_score" in prompt
    assert "lead_summary" in prompt
    assert "recommended_action" in prompt
    assert "followup_email_draft" in prompt
    assert "analysis_method" in prompt
    assert "confidence" in prompt
