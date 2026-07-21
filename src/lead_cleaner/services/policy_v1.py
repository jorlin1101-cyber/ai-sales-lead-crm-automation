from lead_cleaner.schemas.policy import (
    CustomerKind,
    DecisionIntentLevel,
    Disposition,
    LeadDecision,
    LeadFeatures,
    LeadSubtype,
    LeadType,
    ScoreComponent,
    SecuritySignals,
)


POLICY_VERSION = "policy-v1"

CUSTOMER_FIT_SCORES: dict[CustomerKind, int] = {
    "agency": 30,
    "operator": 30,
    "school": 25,
    "corporate": 25,
    "influencer": 20,
    "individual": 10,
    "unknown": 0,
}

B2B_SUBTYPE_BY_CUSTOMER_KIND: dict[CustomerKind, LeadSubtype] = {
    "agency": "Agency",
    "operator": "Operator",
    "school": "School",
    "corporate": "Corporate",
    "influencer": "Influencer",
}


def score_customer_fit(features: LeadFeatures) -> ScoreComponent:
    points = CUSTOMER_FIT_SCORES[features.customer_kind]
    return ScoreComponent(
        component="customer_fit",
        points=points,
        max_points=30,
        reason_codes=[f"customer_kind_{features.customer_kind}"],
    )


def score_intent_strength(features: LeadFeatures) -> ScoreComponent:
    matched_signals: list[str] = []

    if features.asks_for_price:
        matched_signals.append("asks_for_price")
    if features.asks_for_availability:
        matched_signals.append("asks_for_availability")
    if features.mentions_specific_dates:
        matched_signals.append("mentions_specific_dates")
    if features.requests_private_or_custom_service:
        matched_signals.append("requests_private_or_custom_service")
    if features.requests_partnership:
        matched_signals.append("requests_partnership")

    if features.requests_partnership or len(matched_signals) >= 3:
        points = 30
    elif len(matched_signals) == 2:
        points = 22
    elif len(matched_signals) == 1:
        points = 12
    else:
        points = 5

    return ScoreComponent(
        component="intent_strength",
        points=points,
        max_points=30,
        reason_codes=matched_signals or ["no_explicit_intent_signal"],
    )


def score_order_value(features: LeadFeatures) -> ScoreComponent:
    group_size = features.group_size
    reason_codes: list[str] = []

    if features.requests_partnership or (group_size is not None and group_size >= 10):
        points = 25
        if features.requests_partnership:
            reason_codes.append("partnership_request")
        if group_size is not None and group_size >= 10:
            reason_codes.append("group_size_at_least_10")
    elif features.requests_private_or_custom_service or (
        group_size is not None and 4 <= group_size <= 9
    ):
        points = 18
        if features.requests_private_or_custom_service:
            reason_codes.append("private_or_custom_service")
        if group_size is not None and 4 <= group_size <= 9:
            reason_codes.append("group_size_4_to_9")
    elif (group_size is not None and 1 <= group_size <= 3) or features.destinations:
        points = 10
        if group_size is not None and 1 <= group_size <= 3:
            reason_codes.append("group_size_1_to_3")
        if features.destinations:
            reason_codes.append("destination_known")
    else:
        points = 5
        reason_codes.append("order_value_unknown")

    return ScoreComponent(
        component="order_value_proxy",
        points=points,
        max_points=25,
        reason_codes=reason_codes,
    )


def score_information_completeness(features: LeadFeatures) -> ScoreComponent:
    points = 0
    reason_codes: list[str] = []

    if features.company_name_present:
        points += 3
        reason_codes.append("company_name_present")

    if features.cleaned_message_length >= 30:
        points += 4
        reason_codes.append("message_length_at_least_30")

    if features.group_size is not None:
        points += 3
        reason_codes.append("group_size_known")

    if features.mentions_specific_dates:
        points += 3
        reason_codes.append("specific_dates_known")

    if features.destinations:
        points += 2
        reason_codes.append("destination_known")

    return ScoreComponent(
        component="information_completeness",
        points=points,
        max_points=15,
        reason_codes=reason_codes or ["minimal_information"],
    )


def map_score_to_intent(lead_score: int) -> DecisionIntentLevel:
    if not 0 <= lead_score <= 100:
        raise ValueError("lead_score must be between 0 and 100")

    if lead_score >= 75:
        return "High"
    if lead_score >= 45:
        return "Medium"
    return "Low"


def classify_lead(features: LeadFeatures) -> tuple[LeadType, LeadSubtype]:
    b2b_subtype = B2B_SUBTYPE_BY_CUSTOMER_KIND.get(features.customer_kind)
    if b2b_subtype is not None:
        return "B2B", b2b_subtype

    if features.customer_kind == "individual":
        if features.group_size is not None and features.group_size >= 10:
            return "B2C", "LargeGroup"
        if features.requests_private_or_custom_service:
            return "B2C", "PrivateCustom"
        return "B2C", "FIT"

    return "Unknown", "Unknown"


def information_is_severely_insufficient(features: LeadFeatures) -> bool:
    has_intent_signal = any(
        (
            features.asks_for_price,
            features.asks_for_availability,
            features.mentions_specific_dates,
            features.requests_private_or_custom_service,
            features.requests_partnership,
        )
    )
    has_order_detail = features.group_size is not None or bool(features.destinations)

    return (
        not features.company_name_present
        and features.cleaned_message_length < 30
        and not has_intent_signal
        and not has_order_detail
    )


def security_review_reasons(security_signals: SecuritySignals) -> list[str]:
    review_reasons: list[str] = []
    if security_signals.injection_suspected:
        review_reasons.append("prompt_injection_suspected")
    if security_signals.knowledge_injection_suspected:
        review_reasons.append("knowledge_injection_suspected")
    return review_reasons


def decide_disposition(
    features: LeadFeatures,
    security_signals: SecuritySignals,
    lead_score: int,
) -> tuple[Disposition, bool, list[str]]:
    review_reasons = security_review_reasons(security_signals)
    if review_reasons:
        return "manual_review", True, review_reasons

    if features.customer_kind == "unknown":
        return "manual_review", True, ["unknown_customer_kind"]

    if features.conflict_codes:
        return "manual_review", True, list(features.conflict_codes)

    if information_is_severely_insufficient(features):
        return "manual_review", True, ["insufficient_information"]

    if lead_score >= 65:
        return "qualified", False, []

    return "nurture", False, []


def build_spam_decision(
    features: LeadFeatures,
    security_signals: SecuritySignals,
) -> LeadDecision:
    lead_type, lead_subtype = classify_lead(features)
    review_reasons = security_review_reasons(security_signals)

    return LeadDecision(
        lead_type=lead_type,
        lead_subtype=lead_subtype,
        disposition="spam",
        intent_level="Low",
        lead_score=0,
        score_breakdown=[
            ScoreComponent(
                component="spam_override",
                points=0,
                max_points=0,
                reason_codes=["spam_or_promotion_detected"],
            )
        ],
        needs_review=bool(review_reasons),
        review_reasons=review_reasons,
        policy_version=POLICY_VERSION,
    )


def evaluate_policy(
    features: LeadFeatures,
    security_signals: SecuritySignals,
) -> LeadDecision:
    if features.contains_spam_or_promotion:
        return build_spam_decision(features, security_signals)

    score_breakdown = [
        score_customer_fit(features),
        score_intent_strength(features),
        score_order_value(features),
        score_information_completeness(features),
    ]
    lead_score = sum(component.points for component in score_breakdown)
    intent_level = map_score_to_intent(lead_score)
    lead_type, lead_subtype = classify_lead(features)
    disposition, needs_review, review_reasons = decide_disposition(
        features=features,
        security_signals=security_signals,
        lead_score=lead_score,
    )

    return LeadDecision(
        lead_type=lead_type,
        lead_subtype=lead_subtype,
        disposition=disposition,
        intent_level=intent_level,
        lead_score=lead_score,
        score_breakdown=score_breakdown,
        needs_review=needs_review,
        review_reasons=review_reasons,
        policy_version=POLICY_VERSION,
    )
