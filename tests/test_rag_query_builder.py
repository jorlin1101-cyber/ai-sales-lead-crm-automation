from lead_cleaner.rag.query_builder import build_lead_features_query
from lead_cleaner.schemas.policy import LeadFeatures


def test_query_builder_uses_features_in_stable_order() -> None:
    features = LeadFeatures(
        customer_kind="agency",
        destinations=["Western Sichuan", "Tibet", "Western Sichuan"],
        group_size=20,
        requests_private_or_custom_service=True,
        asks_for_price=True,
        asks_for_availability=True,
        mentions_specific_dates=True,
        requests_partnership=True,
    )

    query = build_lead_features_query(features)

    assert query == (
        "travel agency | destinations Western Sichuan Tibet | group size 20 people | "
        "private custom tour | pricing quotation cost | availability booking | "
        "specific travel dates | travel partnership"
    )


def test_query_builder_does_not_include_server_scoring_facts() -> None:
    features = LeadFeatures(
        customer_kind="individual",
        company_name_present=True,
        cleaned_message_length=5000,
        conflict_codes=["multiple_customer_kinds"],
    )

    query = build_lead_features_query(features)

    assert query == "individual traveler"
    assert "5000" not in query
    assert "conflict" not in query


def test_unknown_minimal_features_use_general_query() -> None:
    features = LeadFeatures(customer_kind="unknown")

    assert build_lead_features_query(features) == ("traveler | general travel product information")
