from lead_cleaner.services.scoring import (
    calculate_customer_type_score,
    calculate_information_completeness_score,
    calculate_intent_score,
    map_score_to_intent_level,
    calculate_order_value_score,
    detect_lead_type_and_subtype,
    score_lead,
)
from lead_cleaner.schemas.lead import CleanedLead


def test_detect_lead_type_and_subtype_b2b_agency():
    lead_data = {
        "name": "John Doe",
        "email": "john.doe@example.com",
        "message": "I am a travel agency looking for a corporate retreat."
    }
    lead_type, lead_subtype = detect_lead_type_and_subtype(lead_data["message"])
    assert lead_type == "B2B"
    assert lead_subtype == "Agency"

def test_detect_lead_type_and_subtype_b2b_operator():
    lead_data = {
        "name": "Jane Smith",
        "email": "jane.smith@example.com",
        "message": "I am a tour operator looking for a business meeting."
    }
    lead_type, lead_subtype = detect_lead_type_and_subtype(lead_data["message"])
    assert lead_type == "B2B"
    assert lead_subtype == "Operator"

def test_detect_lead_type_and_subtype_b2b_school():
    lead_data = {
        "name": "Alice Johnson",
        "email": "alice.johnson@example.com",
        "message": "I am a teacher looking for a school trip."
    }
    lead_type, lead_subtype = detect_lead_type_and_subtype(lead_data["message"])
    assert lead_type == "B2B"
    assert lead_subtype == "School"

def test_detect_lead_type_and_subtype_b2b_corporate():
    lead_data = {
        "name": "Bob Brown",
        "email": "bob.brown@example.com",
        "message": "I am a corporate executive looking for a business retreat."
    }
    lead_type, lead_subtype = detect_lead_type_and_subtype(lead_data["message"])
    assert lead_type == "B2B"
    assert lead_subtype == "Corporate"


def test_detect_lead_type_and_subtype_b2b_influencer():
    lead_data = {
        "name": "Charlie Davis",
        "email": "charlie.davis@example.com",
        "message": "I am a social media influencer looking for a brand partnership."
    }
    lead_type, lead_subtype = detect_lead_type_and_subtype(lead_data["message"])
    assert lead_type == "B2B"
    assert lead_subtype == "Influencer"


def test_detect_lead_type_and_subtype_b2c_large_group():
    lead_data = {
        "name": "Diana Evans",
        "email": "diana.evans@example.com",
        "message": "We are a family group of 20 people planning a private tour in China."
    }
    lead_type, lead_subtype = detect_lead_type_and_subtype(lead_data["message"])
    assert lead_type == "B2C"
    assert lead_subtype == "LargeGroup"


def test_detect_lead_type_and_subtype_b2c_private_custom():
    lead_data = {
        "name": "Ethan Foster",
        "email": "ethan.foster@example.com",
        "message": "I am looking for a personalized service."
    }
    lead_type, lead_subtype = detect_lead_type_and_subtype(lead_data["message"])
    assert lead_type == "B2C"
    assert lead_subtype == "PrivateCustom"


def test_detect_lead_type_and_subtype_b2c_luxury():
    lead_data = {
        "name": "Fiona Green",
        "email": "fiona.green@example.com",
        "message": "I am a luxury brand looking for a high-end partnership."
    }
    lead_type, lead_subtype = detect_lead_type_and_subtype(lead_data["message"])
    assert lead_type == "B2C"
    assert lead_subtype == "LuxuryHighBudget"


def test_detect_lead_type_and_subtype_b2c_FIT():
    lead_data = {
        "name": "George Harris",
        "email": "george.harris@example.com",
        "message": "I am a travel with my family."
    }
    lead_type, lead_subtype = detect_lead_type_and_subtype(lead_data["message"])
    assert lead_type == "B2C"
    assert lead_subtype == "FIT"

def test_detect_lead_type_and_subtype_unknown():
    lead_data = {
        "name": "Hannah Lee",
        "email": "hannah.lee@example.com",
        "message": "random weak text with no clear type."
    }
    lead_type, lead_subtype = detect_lead_type_and_subtype(lead_data["message"])
    assert lead_type == "Unknown"
    assert lead_subtype == "Unknown"


def test_calculate_customer_type_score_high_value_subtypes():
    assert calculate_customer_type_score("Agency") == 30
    assert calculate_customer_type_score("Operator") == 30
    assert calculate_customer_type_score("LargeGroup") == 30


def test_calculate_customer_type_score_medium_high_value_subtypes():
    assert calculate_customer_type_score("School") == 25
    assert calculate_customer_type_score("Corporate") == 25
    assert calculate_customer_type_score("Influencer") == 25
    assert calculate_customer_type_score("PrivateCustom") == 25
    assert calculate_customer_type_score("LuxuryHighBudget") == 25


def test_calculate_customer_type_score_fit():
    assert calculate_customer_type_score("FIT") == 10


def test_calculate_customer_type_score_unknown_or_invalid():
    assert calculate_customer_type_score("Unknown") == 0
    assert calculate_customer_type_score("RandomSubtype") == 0


def test_calculate_intent_score_high_intent():
    assert calculate_intent_score("We want a quotation for a private China tour.") == 30
    assert calculate_intent_score("We are ready to book.") == 30


def test_calculate_intent_score_medium_intent():
    assert calculate_intent_score("Can you send more information?") == 18
    assert calculate_intent_score("I have a question about the itinerary.") == 18


def test_calculate_intent_score_low_intent():
    assert calculate_intent_score("Hello, I found your website.") == 5


def test_calculate_intent_score_high_priority_over_medium():
    assert calculate_intent_score("Can you send a quotation?") == 30


def test_calculate_order_value_score_high_value():
    assert calculate_order_value_score("We want a luxury private tour.") == 25
    assert calculate_order_value_score("We are planning a long-term partnership.") == 25
    assert calculate_order_value_score("We need a 15 days multi-day China itinerary.") == 25


def test_calculate_order_value_score_medium_value():
    assert calculate_order_value_score("We are a family looking for an itinerary.") == 15
    assert calculate_order_value_score("We need a private guide.") == 15
    assert calculate_order_value_score("We are a couple looking for a custom tour.") == 15


def test_calculate_order_value_score_low_value():
    assert calculate_order_value_score("Hello, I found your website.") == 5


def test_calculate_order_value_score_high_priority_over_medium():
    assert (
        calculate_order_value_score(
            "We are a family looking for a luxury private tour."
        )
        == 25
    )


def test_calculate_information_completeness_score_full_information():
    score = calculate_information_completeness_score(
        company_name="Spain Travel Agency",
        message=(
            "We are a group of 20 people planning a private tour "
            "to China in September with a clear budget."
        ),
    )

    assert score == 15


def test_calculate_information_completeness_score_without_company_name():
    score = calculate_information_completeness_score(
        company_name="",
        message=(
            "We are a group of 20 people planning a private tour "
            "to China in September."
        ),
    )

    assert score == 12


def test_calculate_information_completeness_score_short_message():
    score = calculate_information_completeness_score(
        company_name="Spain Travel Agency",
        message="Interested.",
    )

    assert score == 3


def test_calculate_information_completeness_score_empty_message_and_company():
    score = calculate_information_completeness_score(
        company_name="",
        message="",
    )

    assert score == 0


def test_map_score_to_intent_level_high():
    assert map_score_to_intent_level(75) == "High"
    assert map_score_to_intent_level(100) == "High"


def test_map_score_to_intent_level_medium():
    assert map_score_to_intent_level(45) == "Medium"
    assert map_score_to_intent_level(74) == "Medium"


def test_map_score_to_intent_level_low():
    assert map_score_to_intent_level(0) == "Low"
    assert map_score_to_intent_level(44) == "Low"


def test_score_lead_high_value_b2b_agency():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="John Doe",
        email="john@example.com",
        company_name="Spain Travel Agency",
        message=(
            "We want a quotation for a 20 people private tour "
            "to China in September."
        ),
        source="Website",
    )

    result = score_lead(cleaned_lead)

    assert result.lead_type == "B2B"
    assert result.lead_subtype == "Agency"
    assert result.intent_level == "High"
    assert result.lead_score >= 75


def test_score_lead_high_value_b2c_large_group():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="Diana Evans",
        email="diana@example.com",
        company_name="",
        message=(
            "We are a family group of 20 people planning a private tour "
            "in China next October."
        ),
        source="Website",
    )

    result = score_lead(cleaned_lead)

    assert result.lead_type == "B2C"
    assert result.lead_subtype == "LargeGroup"
    assert result.intent_level == "High"
    assert result.lead_score >= 75


def test_score_lead_low_value_fit():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="George Harris",
        email="george@example.com",
        company_name="",
        message="I want to travel with my family.",
        source="Website",
    )

    result = score_lead(cleaned_lead)

    assert result.lead_type == "B2C"
    assert result.lead_subtype == "FIT"
    assert result.intent_level == "Low"
    assert result.lead_score < 45


def test_score_lead_unknown_weak_text():
    cleaned_lead = CleanedLead(
        lead_id="12345",
        name="Hannah Lee",
        email="hannah@example.com",
        company_name="",
        message="Hello, I found your website.",
        source="Website",
    )

    result = score_lead(cleaned_lead)

    assert result.lead_type == "Unknown"
    assert result.lead_subtype == "Unknown"
    assert result.intent_level == "Low"
    assert result.lead_score < 45
