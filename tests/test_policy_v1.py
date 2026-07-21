import pytest

from lead_cleaner.schemas.policy import CustomerKind, LeadFeatures, SecuritySignals
from lead_cleaner.services.policy_v1 import (
    classify_lead,
    decide_disposition,
    evaluate_policy,
    map_score_to_intent,
    score_customer_fit,
    score_information_completeness,
    score_intent_strength,
    score_order_value,
)


def make_features(**overrides: object) -> LeadFeatures:
    data: dict[str, object] = {
        "customer_kind": "individual",
        "company_name_present": True,
        "cleaned_message_length": 60,
    }
    data.update(overrides)
    return LeadFeatures.model_validate(data)


@pytest.mark.parametrize(
    ("customer_kind", "expected_points"),
    [
        ("agency", 30),
        ("operator", 30),
        ("school", 25),
        ("corporate", 25),
        ("influencer", 20),
        ("individual", 10),
        ("unknown", 0),
    ],
)
def test_customer_fit_decision_table(
    customer_kind: CustomerKind,
    expected_points: int,
):
    component = score_customer_fit(make_features(customer_kind=customer_kind))

    assert component.points == expected_points
    assert component.max_points == 30
    assert component.reason_codes == [f"customer_kind_{customer_kind}"]


@pytest.mark.parametrize(
    ("feature_overrides", "expected_points"),
    [
        ({}, 5),
        ({"asks_for_price": True}, 12),
        ({"asks_for_price": True, "asks_for_availability": True}, 22),
        (
            {
                "asks_for_price": True,
                "asks_for_availability": True,
                "mentions_specific_dates": True,
            },
            30,
        ),
        ({"requests_partnership": True}, 30),
    ],
)
def test_intent_strength_uses_signal_count_and_partnership_override(
    feature_overrides: dict[str, object],
    expected_points: int,
):
    component = score_intent_strength(make_features(**feature_overrides))

    assert component.points == expected_points
    assert component.max_points == 30


@pytest.mark.parametrize(
    ("feature_overrides", "expected_points"),
    [
        ({}, 5),
        ({"destinations": ["Chengdu"]}, 10),
        ({"group_size": 1}, 10),
        ({"group_size": 3}, 10),
        ({"group_size": 4}, 18),
        ({"group_size": 9}, 18),
        ({"group_size": 10}, 25),
        ({"requests_private_or_custom_service": True}, 18),
        ({"requests_partnership": True}, 25),
    ],
)
def test_order_value_boundaries(
    feature_overrides: dict[str, object],
    expected_points: int,
):
    component = score_order_value(make_features(**feature_overrides))

    assert component.points == expected_points
    assert component.max_points == 25


def test_order_value_records_all_reasons_at_the_winning_priority():
    component = score_order_value(
        make_features(
            group_size=12,
            requests_partnership=True,
            destinations=["Tibet"],
        )
    )

    assert component.points == 25
    assert component.reason_codes == ["partnership_request", "group_size_at_least_10"]


def test_information_completeness_can_reach_full_score():
    component = score_information_completeness(
        make_features(
            group_size=12,
            mentions_specific_dates=True,
            destinations=["Chengdu"],
        )
    )

    assert component.points == 15
    assert component.reason_codes == [
        "company_name_present",
        "message_length_at_least_30",
        "group_size_known",
        "specific_dates_known",
        "destination_known",
    ]


def test_information_completeness_can_be_zero():
    component = score_information_completeness(
        make_features(
            company_name_present=False,
            cleaned_message_length=10,
        )
    )

    assert component.points == 0
    assert component.reason_codes == ["minimal_information"]


@pytest.mark.parametrize(
    ("lead_score", "expected_intent"),
    [
        (0, "Low"),
        (44, "Low"),
        (45, "Medium"),
        (74, "Medium"),
        (75, "High"),
        (100, "High"),
    ],
)
def test_intent_level_boundaries(lead_score: int, expected_intent: str):
    assert map_score_to_intent(lead_score) == expected_intent


@pytest.mark.parametrize("invalid_score", [-1, 101])
def test_intent_mapping_rejects_scores_outside_policy_range(invalid_score: int):
    with pytest.raises(ValueError, match="lead_score must be between 0 and 100"):
        map_score_to_intent(invalid_score)


@pytest.mark.parametrize(
    ("features", "expected_classification"),
    [
        (make_features(customer_kind="agency"), ("B2B", "Agency")),
        (make_features(customer_kind="operator"), ("B2B", "Operator")),
        (make_features(customer_kind="school"), ("B2B", "School")),
        (make_features(customer_kind="corporate"), ("B2B", "Corporate")),
        (make_features(customer_kind="influencer"), ("B2B", "Influencer")),
        (make_features(customer_kind="individual", group_size=10), ("B2C", "LargeGroup")),
        (
            make_features(
                customer_kind="individual",
                requests_private_or_custom_service=True,
            ),
            ("B2C", "PrivateCustom"),
        ),
        (make_features(customer_kind="individual"), ("B2C", "FIT")),
        (make_features(customer_kind="unknown"), ("Unknown", "Unknown")),
    ],
)
def test_lead_classification(features: LeadFeatures, expected_classification: tuple[str, str]):
    assert classify_lead(features) == expected_classification


def test_disposition_uses_qualified_boundary_of_65():
    features = make_features()
    signals = SecuritySignals()

    assert decide_disposition(features, signals, 64) == ("nurture", False, [])
    assert decide_disposition(features, signals, 65) == ("qualified", False, [])


def test_injection_takes_priority_over_score():
    result = decide_disposition(
        features=make_features(customer_kind="agency"),
        security_signals=SecuritySignals(
            injection_suspected=True,
            matched_pattern_codes=["set_score_100_en"],
        ),
        lead_score=100,
    )

    assert result == ("manual_review", True, ["prompt_injection_suspected"])


def test_unknown_customer_kind_requires_review_but_is_not_spam():
    decision = evaluate_policy(
        features=make_features(customer_kind="unknown"),
        security_signals=SecuritySignals(),
    )

    assert decision.disposition == "manual_review"
    assert decision.needs_review is True
    assert decision.review_reasons == ["unknown_customer_kind"]
    assert decision.lead_score > 0


def test_feature_conflicts_require_review():
    result = decide_disposition(
        features=make_features(conflict_codes=["multiple_customer_kinds"]),
        security_signals=SecuritySignals(),
        lead_score=80,
    )

    assert result == ("manual_review", True, ["multiple_customer_kinds"])


def test_severely_insufficient_information_requires_review_for_every_extractor():
    result = decide_disposition(
        features=make_features(
            company_name_present=False,
            cleaned_message_length=10,
        ),
        security_signals=SecuritySignals(),
        lead_score=20,
    )

    assert result == ("manual_review", True, ["insufficient_information"])


def test_spam_override_forces_zero_score_and_skips_normal_breakdown():
    decision = evaluate_policy(
        features=make_features(
            customer_kind="agency",
            contains_spam_or_promotion=True,
            asks_for_price=True,
            requests_partnership=True,
        ),
        security_signals=SecuritySignals(),
    )

    assert decision.lead_score == 0
    assert decision.intent_level == "Low"
    assert decision.disposition == "spam"
    assert [item.component for item in decision.score_breakdown] == ["spam_override"]
    assert decision.needs_review is False


def test_spam_with_injection_stays_spam_but_retains_review_flag():
    decision = evaluate_policy(
        features=make_features(contains_spam_or_promotion=True),
        security_signals=SecuritySignals(injection_suspected=True),
    )

    assert decision.disposition == "spam"
    assert decision.lead_score == 0
    assert decision.needs_review is True
    assert decision.review_reasons == ["prompt_injection_suspected"]


def test_complete_high_value_agency_lead_is_qualified_with_full_breakdown():
    features = make_features(
        customer_kind="agency",
        group_size=12,
        mentions_specific_dates=True,
        asks_for_price=True,
        requests_private_or_custom_service=True,
        destinations=["Chengdu"],
    )

    decision = evaluate_policy(features, SecuritySignals())

    assert decision.lead_score == 100
    assert decision.intent_level == "High"
    assert decision.disposition == "qualified"
    assert decision.lead_type == "B2B"
    assert decision.lead_subtype == "Agency"
    assert [item.component for item in decision.score_breakdown] == [
        "customer_fit",
        "intent_strength",
        "order_value_proxy",
        "information_completeness",
    ]
    assert sum(item.points for item in decision.score_breakdown) == decision.lead_score
    assert decision.policy_version == "policy-v1"


def test_same_policy_inputs_always_produce_identical_decisions():
    features = make_features(
        customer_kind="corporate",
        group_size=8,
        asks_for_availability=True,
        mentions_specific_dates=True,
        destinations=["Yunnan"],
    )
    signals = SecuritySignals()

    first = evaluate_policy(features, signals)
    second = evaluate_policy(features, signals)

    assert first == second
    assert first.model_dump() == second.model_dump()
