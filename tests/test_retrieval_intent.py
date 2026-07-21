import pytest
from pydantic import ValidationError

from lead_cleaner.rag.retrieval_intent import (
    build_retrieval_intent,
    build_retrieval_intent_query,
    build_retrieval_queries,
    sanitize_original_retrieval_query,
)
from lead_cleaner.rag.schemas import RetrievalIntent
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import LeadFeatures


def make_lead(message: str) -> CleanedLead:
    return CleanedLead(
        lead_id="lead-1",
        name="Evaluation Lead",
        email="eval@example.com",
        company_name="",
        message=message,
        source="test",
    )


def test_retrieval_intent_adds_topics_missing_from_scoring_features() -> None:
    lead = make_lead(
        "Do foreign travelers need a permit to visit Tibet, and when is the deposit due?"
    )
    features = LeadFeatures(
        customer_kind="individual",
        destinations=["Tibet"],
        language="en",
    )

    intent = build_retrieval_intent(lead, features)

    assert intent.topic_codes == ["payment_policy", "travel_permit"]
    assert build_retrieval_intent_query(intent) == (
        "individual traveler | destinations Tibet | payment policy deposit final balance | "
        "travel permit entry requirements foreign travelers"
    )


def test_feature_backed_topics_and_chinese_retrieval_terms_are_deterministic() -> None:
    lead = make_lead("云南适合带小朋友去吗？我们不想行程太赶，价格是多少？")
    features = LeadFeatures(
        customer_kind="individual",
        destinations=["Yunnan"],
        asks_for_price=True,
        language="zh",
    )

    intent = build_retrieval_intent(lead, features)

    assert intent.topic_codes == ["pricing", "family_travel", "flexible_pacing"]
    assert build_retrieval_intent_query(intent) == (
        "individual traveler | destinations Yunnan | pricing quotation cost factors | "
        "family children suitable tour | flexible pacing not rushed"
    )


def test_original_query_removes_obvious_contact_data_but_keeps_question() -> None:
    message = (
        "Email john@example.com or call +86 138-0013-8000. "
        "Do we need a Tibet permit? See https://example.com/profile"
    )

    sanitized = sanitize_original_retrieval_query(message)

    assert sanitized == "Email or call . Do we need a Tibet permit? See"
    assert "john@example.com" not in sanitized
    assert "138-0013-8000" not in sanitized
    assert "https://" not in sanitized


def test_query_plan_preserves_original_meaning_and_adds_structured_terms() -> None:
    lead = make_lead("Do foreign travelers need a permit to visit Tibet?")
    features = LeadFeatures(
        customer_kind="individual",
        destinations=["Tibet"],
        language="en",
    )

    queries = build_retrieval_queries(lead, features)

    assert queries == [
        "Do foreign travelers need a permit to visit Tibet?",
        (
            "individual traveler | destinations Tibet | "
            "travel permit entry requirements foreign travelers"
        ),
    ]


def test_retrieval_intent_forbids_unowned_fields() -> None:
    with pytest.raises(ValidationError) as error:
        RetrievalIntent.model_validate(
            {
                "customer_kind": "individual",
                "raw_message": "must not be persisted in the intent",
            }
        )

    assert any(item["type"] == "extra_forbidden" for item in error.value.errors())
