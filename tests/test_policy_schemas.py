import pytest
from pydantic import ValidationError

from lead_cleaner.schemas.policy import (
    ExtractedLeadFeatures,
    LeadDecision,
    LeadFeatures,
    ScoreComponent,
    SecuritySignals,
)


def valid_score_breakdown() -> list[ScoreComponent]:
    return [
        ScoreComponent(
            component="customer_fit",
            points=30,
            max_points=30,
            reason_codes=["customer_kind_agency"],
        ),
        ScoreComponent(
            component="intent_strength",
            points=22,
            max_points=30,
            reason_codes=["asks_for_price", "mentions_specific_dates"],
        ),
        ScoreComponent(
            component="order_value_proxy",
            points=18,
            max_points=25,
            reason_codes=["private_or_custom_service"],
        ),
        ScoreComponent(
            component="information_completeness",
            points=12,
            max_points=15,
            reason_codes=["company_name_present", "message_length_at_least_30"],
        ),
    ]


def valid_decision_data() -> dict[str, object]:
    return {
        "lead_type": "B2B",
        "lead_subtype": "Agency",
        "disposition": "qualified",
        "intent_level": "High",
        "lead_score": 82,
        "score_breakdown": valid_score_breakdown(),
        "needs_review": False,
        "review_reasons": [],
        "policy_version": "policy-v1",
    }


def test_lead_features_accepts_canonical_business_facts():
    features = LeadFeatures(
        customer_kind="agency",
        group_size=12,
        mentions_specific_dates=True,
        asks_for_price=True,
        requests_private_or_custom_service=True,
        destinations=["Chengdu", "Tibet"],
        language="en",
        company_name_present=True,
        cleaned_message_length=120,
    )

    assert features.customer_kind == "agency"
    assert features.group_size == 12
    assert features.destinations == ["Chengdu", "Tibet"]
    assert features.conflict_codes == []


def test_extracted_lead_features_accepts_only_extractor_owned_facts():
    extracted = ExtractedLeadFeatures(
        customer_kind="agency",
        group_size=12,
        mentions_specific_dates=True,
        asks_for_price=True,
        asks_for_availability=True,
        requests_private_or_custom_service=True,
        requests_partnership=False,
        contains_spam_or_promotion=False,
        destinations=["Chengdu"],
        language="en",
    )

    assert extracted.customer_kind == "agency"
    assert extracted.group_size == 12
    assert extracted.destinations == ["Chengdu"]
    assert "company_name_present" not in extracted.model_fields_set


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("company_name_present", True),
        ("cleaned_message_length", 120),
        ("conflict_codes", []),
        ("lead_score", 100),
        ("intent_level", "High"),
        ("disposition", "qualified"),
        ("policy_version", "policy-v1"),
        ("analysis_method", "llm_features"),
        ("provider", "openai"),
    ],
)
def test_extracted_lead_features_rejects_server_and_decision_fields(
    field_name: str,
    field_value: object,
):
    with pytest.raises(ValidationError) as exc_info:
        ExtractedLeadFeatures.model_validate(
            {
                "customer_kind": "agency",
                field_name: field_value,
            }
        )

    assert any(
        error["type"] == "extra_forbidden" and error["loc"] == (field_name,)
        for error in exc_info.value.errors()
    )


def test_lead_features_extends_extracted_features_with_server_owned_facts():
    extracted = ExtractedLeadFeatures(
        customer_kind="operator",
        group_size=20,
        asks_for_price=True,
        destinations=["Sichuan"],
        language="en",
    )

    features = LeadFeatures.model_validate(
        {
            **extracted.model_dump(),
            "company_name_present": True,
            "cleaned_message_length": 90,
            "conflict_codes": [],
        }
    )

    assert isinstance(features, ExtractedLeadFeatures)
    assert features.customer_kind == "operator"
    assert features.company_name_present is True
    assert features.cleaned_message_length == 90


def test_lead_features_rejects_unknown_fields():
    with pytest.raises(ValidationError) as exc_info:
        LeadFeatures.model_validate(
            {
                "customer_kind": "agency",
                "lead_score": 100,
            }
        )

    assert any(error["type"] == "extra_forbidden" for error in exc_info.value.errors())


def test_security_signal_lists_are_not_shared_between_instances():
    first = SecuritySignals()
    second = SecuritySignals()

    first.matched_pattern_codes.append("ignore_previous_instructions")

    assert first.matched_pattern_codes == ["ignore_previous_instructions"]
    assert second.matched_pattern_codes == []


def test_score_component_accepts_points_within_maximum():
    component = ScoreComponent(
        component="customer_fit",
        points=25,
        max_points=30,
        reason_codes=["customer_kind_corporate"],
    )

    assert component.points == 25
    assert component.max_points == 30


def test_score_component_rejects_points_above_maximum():
    with pytest.raises(ValidationError, match="points cannot exceed max_points"):
        ScoreComponent(
            component="customer_fit",
            points=31,
            max_points=30,
        )


def test_lead_decision_accepts_consistent_breakdown():
    decision = LeadDecision.model_validate(valid_decision_data())

    assert decision.lead_score == 82
    assert len(decision.score_breakdown) == 4
    assert decision.policy_version == "policy-v1"


def test_lead_decision_rejects_breakdown_total_mismatch():
    data = valid_decision_data()
    data["lead_score"] = 81

    with pytest.raises(
        ValidationError,
        match="score_breakdown points must sum to lead_score",
    ):
        LeadDecision.model_validate(data)


def test_lead_decision_rejects_duplicate_components():
    data = valid_decision_data()
    breakdown = valid_score_breakdown()
    breakdown[1] = ScoreComponent(
        component="customer_fit",
        points=22,
        max_points=30,
        reason_codes=["duplicate_for_test"],
    )
    data["score_breakdown"] = breakdown

    with pytest.raises(
        ValidationError,
        match="score_breakdown cannot contain duplicate components",
    ):
        LeadDecision.model_validate(data)


@pytest.mark.parametrize(
    ("needs_review", "review_reasons", "disposition"),
    [
        (True, [], "manual_review"),
        (False, ["prompt_injection_suspected"], "qualified"),
        (False, [], "manual_review"),
    ],
)
def test_lead_decision_rejects_inconsistent_review_fields(
    needs_review: bool,
    review_reasons: list[str],
    disposition: str,
):
    data = valid_decision_data()
    data.update(
        {
            "needs_review": needs_review,
            "review_reasons": review_reasons,
            "disposition": disposition,
        }
    )

    with pytest.raises(ValidationError):
        LeadDecision.model_validate(data)


def test_lead_decision_rejects_unrecognized_subtype():
    data = valid_decision_data()
    data["lead_subtype"] = "SuperVIPMaybe"

    with pytest.raises(ValidationError):
        LeadDecision.model_validate(data)
