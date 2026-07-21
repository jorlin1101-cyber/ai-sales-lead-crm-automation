from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import ExtractedLeadFeatures, LeadFeatures
from lead_cleaner.services.lead_feature_merger import (
    merge_extracted_features_with_server_facts,
)


def make_cleaned_lead(
    message: str = "We need a private Sichuan tour for 20 clients next October.",
    *,
    company_name: str = "Example Travel Agency",
) -> CleanedLead:
    return CleanedLead(
        lead_id="lead-feature-merge-test",
        external_lead_id="external-feature-merge-test",
        name="Test Person",
        email="test.person@example.com",
        company_name=company_name,
        message=message,
        source="Website",
    )


def make_extracted_features() -> ExtractedLeadFeatures:
    return ExtractedLeadFeatures(
        customer_kind="operator",
        group_size=8,
        asks_for_price=True,
        destinations=["Tibet"],
        language="en",
    )


def test_merge_builds_canonical_features_and_preserves_extracted_business_facts():
    extracted = make_extracted_features()
    cleaned_lead = make_cleaned_lead()

    features = merge_extracted_features_with_server_facts(extracted, cleaned_lead)

    assert isinstance(features, LeadFeatures)
    assert features.customer_kind == "operator"
    assert features.group_size == 8
    assert features.asks_for_price is True
    assert features.destinations == ["Tibet"]
    assert features.language == "en"


def test_merge_derives_company_presence_and_message_length_from_cleaned_lead():
    extracted = make_extracted_features()
    cleaned_lead = make_cleaned_lead(
        message="  Short inquiry  ",
        company_name="  Example Company  ",
    )

    features = merge_extracted_features_with_server_facts(extracted, cleaned_lead)

    assert features.company_name_present is True
    assert features.cleaned_message_length == len("Short inquiry")


def test_merge_does_not_treat_whitespace_company_as_present():
    features = merge_extracted_features_with_server_facts(
        make_extracted_features(),
        make_cleaned_lead(company_name="   "),
    )

    assert features.company_name_present is False


def test_merge_preserves_deterministic_group_conflicts_for_manual_review():
    extracted = ExtractedLeadFeatures(
        customer_kind="individual",
        group_size=None,
        language="en",
    )
    cleaned_lead = make_cleaned_lead(
        "We currently have 4 people, but another message says 15 travelers.",
        company_name="",
    )

    features = merge_extracted_features_with_server_facts(extracted, cleaned_lead)

    assert features.customer_kind == "individual"
    assert features.group_size is None
    assert features.conflict_codes == ["conflicting_group_sizes"]


def test_merge_preserves_deterministic_customer_kind_conflicts():
    extracted = ExtractedLeadFeatures(
        customer_kind="agency",
        language="en",
    )
    cleaned_lead = make_cleaned_lead(
        "We are a travel agency working with a university student group."
    )

    features = merge_extracted_features_with_server_facts(extracted, cleaned_lead)

    assert features.customer_kind == "agency"
    assert features.conflict_codes == ["multiple_customer_kinds"]


def test_merge_does_not_mutate_its_inputs():
    extracted = make_extracted_features()
    cleaned_lead = make_cleaned_lead()
    original_extracted = extracted.model_dump()
    original_cleaned_lead = cleaned_lead.model_dump()

    merge_extracted_features_with_server_facts(extracted, cleaned_lead)

    assert extracted.model_dump() == original_extracted
    assert cleaned_lead.model_dump() == original_cleaned_lead
