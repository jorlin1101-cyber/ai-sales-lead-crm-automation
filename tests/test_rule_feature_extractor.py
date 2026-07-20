from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.services.rule_feature_extractor import extract_rule_features


def make_cleaned_lead(
    message: str,
    *,
    company_name: str = "",
) -> CleanedLead:
    return CleanedLead(
        lead_id="lead-rule-test",
        name="Test Lead",
        email="lead@example.com",
        company_name=company_name,
        message=message,
        source="Website",
    )


def test_extracts_structured_features_from_english_agency_lead():
    lead = make_cleaned_lead(
        "We need a quotation for a private China tour for 20 clients in September.",
        company_name="Spain Travel Agency",
    )

    features = extract_rule_features(lead)

    assert features.customer_kind == "agency"
    assert features.group_size == 20
    assert features.mentions_specific_dates is True
    assert features.asks_for_price is True
    assert features.requests_private_or_custom_service is True
    assert features.destinations == ["China"]
    assert features.language == "en"
    assert features.company_name_present is True
    assert features.cleaned_message_length == len(lead.message)
    assert features.conflict_codes == []


def test_extracts_minimal_chinese_rules():
    lead = make_cleaned_lead(
        "我们是一家旅行社，想咨询10人川西定制团，计划9月出发，请报价。",
    )

    features = extract_rule_features(lead)

    assert features.customer_kind == "agency"
    assert features.group_size == 10
    assert features.mentions_specific_dates is True
    assert features.asks_for_price is True
    assert features.requests_private_or_custom_service is True
    assert features.destinations == ["Western Sichuan"]
    assert features.language == "zh"


def test_infers_individual_only_when_consumer_travel_evidence_exists():
    consumer = make_cleaned_lead(
        "I will visit Chengdu with my girlfriend and want a private panda tour."
    )
    weak = make_cleaned_lead("Hello, I found your website.")

    assert extract_rule_features(consumer).customer_kind == "individual"
    assert extract_rule_features(weak).customer_kind == "unknown"


def test_extracts_availability_and_partnership_signals():
    lead = make_cleaned_lead(
        "Are you available next month? We want to discuss a long-term cooperation.",
        company_name="Example Travel Agency",
    )

    features = extract_rule_features(lead)

    assert features.asks_for_availability is True
    assert features.mentions_specific_dates is True
    assert features.requests_partnership is True


def test_budget_word_alone_does_not_become_price_request():
    lead = make_cleaned_lead("Our budget has not been decided yet.")

    features = extract_rule_features(lead)

    assert features.asks_for_price is False


def test_conflicting_group_sizes_are_recorded_without_guessing_a_size():
    lead = make_cleaned_lead("We currently have 4 people, but another message says 15 travelers.")

    features = extract_rule_features(lead)

    assert features.group_size is None
    assert features.conflict_codes == ["conflicting_group_sizes"]


def test_multiple_customer_kinds_are_recorded_for_manual_review():
    lead = make_cleaned_lead("We are a travel agency working with a university student group.")

    features = extract_rule_features(lead)

    assert features.customer_kind == "agency"
    assert features.conflict_codes == ["multiple_customer_kinds"]


def test_spam_patterns_set_only_the_spam_feature():
    lead = make_cleaned_lead("We provide SEO service and can promote your website with backlinks.")

    features = extract_rule_features(lead)

    assert features.contains_spam_or_promotion is True
    assert features.customer_kind == "unknown"


def test_company_presence_and_message_length_are_server_derived():
    lead = make_cleaned_lead(
        "Short message",
        company_name="Example Company",
    )

    features = extract_rule_features(lead)

    assert features.company_name_present is True
    assert features.cleaned_message_length == len("Short message")
