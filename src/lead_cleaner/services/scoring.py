from lead_cleaner.schemas.lead import CleanedLead, LeadScoreResult


def detect_lead_type_and_subtype(text: str) -> tuple[str, str]:
    normalized_text = text.lower()

    agency_keywords = ["travel agency", "agency"]
    operator_keywords = ["tour operator", "operator"]
    school_keywords = ["school", "university", "student group"]

    corporate_keywords = [
        "corporate",
        "business trip",
        "company retreat",
        "incentive trip",
        "mice",
        "business meeting",
        "corporate meeting",
        "conference",
    ]

    influencer_keywords = [
        "influencer",
        "blogger",
        "creator",
        "instagram",
        "youtube",
        "tiktok",
        "media kit",
    ]

    large_group_keywords = [
        "large group",
        "family group",
        "friends group",
        "10 people",
        "15 people",
        "20 people",
        "30 people",
        "pax",
    ]

    private_custom_keywords = [
        "private tour",
        "private service",
        "personalized service",
        "custom tour",
        "custom itinerary",
        "tailor-made",
        "personalized itinerary",
        "bespoke",
        "private guide",
        "private driver",
    ]

    luxury_keywords = [
        "luxury",
        "high-end",
        "premium",
        "5-star",
        "boutique hotel",
        "high budget",
        "comfortable hotel",
        "private experience",
    ]

    fit_keywords = [
        "solo",
        "couple",
        "family",
        "my wife",
        "my husband",
        "my parents",
        "with my family",
        "independent traveler",
    ]

    if any(keyword in normalized_text for keyword in agency_keywords):
        return "B2B", "Agency"

    if any(keyword in normalized_text for keyword in operator_keywords):
        return "B2B", "Operator"

    if any(keyword in normalized_text for keyword in school_keywords):
        return "B2B", "School"

    if any(keyword in normalized_text for keyword in corporate_keywords):
        return "B2B", "Corporate"

    if any(keyword in normalized_text for keyword in influencer_keywords):
        return "B2B", "Influencer"

    if any(keyword in normalized_text for keyword in large_group_keywords):
        return "B2C", "LargeGroup"

    if any(keyword in normalized_text for keyword in private_custom_keywords):
        return "B2C", "PrivateCustom"

    if any(keyword in normalized_text for keyword in luxury_keywords):
        return "B2C", "LuxuryHighBudget"

    if any(keyword in normalized_text for keyword in fit_keywords):
        return "B2C", "FIT"

    return "Unknown", "Unknown"


def calculate_customer_type_score(lead_subtype: str) -> int:
    score_map = {
        "Agency": 30,
        "Operator": 30,
        "LargeGroup": 30,
        "School": 25,
        "Corporate": 25,
        "Influencer": 25,
        "PrivateCustom": 25,
        "LuxuryHighBudget": 25,
        "FIT": 10,
        "Other": 0,
        "Unknown": 0,
    }

    return score_map.get(lead_subtype, 0)


def calculate_intent_score(text: str) -> int:
    """
    Calculate intent strength score from lead text.

    High intent: 30
    Medium intent: 18
    Low intent: 5
    """
    normalized_text = text.lower()

    high_intent_keywords = [
        "quotation",
        "quote",
        "book",
        "booking",
        "reserve",
        "partnership",
        "cooperate",
        "collaboration",
        "plan",
        "planning",
        "interested",
        "want to arrange",
        "ready to book",
    ]

    medium_intent_keywords = [
        "ask",
        "question",
        "information",
        "details",
        "learn more",
        "available",
        "possible",
        "can you",
        "could you",
    ]

    if any(keyword in normalized_text for keyword in high_intent_keywords):
        return 30

    if any(keyword in normalized_text for keyword in medium_intent_keywords):
        return 18

    return 5


def calculate_order_value_score(text: str) -> int:
    """
    Calculate order value potential score from lead text.

    High value: 25
    Medium value: 15
    Low value: 5
    """
    normalized_text = text.lower()

    high_value_keywords = [
        "large group",
        "private tour",
        "custom itinerary",
        "luxury",
        "high-end",
        "premium",
        "long-term",
        "partnership",
        "multi-day",
        "15 days",
        "two weeks",
        "budget",
        "5-star",
    ]

    medium_value_keywords = [
        "family",
        "couple",
        "small group",
        "private guide",
        "private driver",
        "custom tour",
        "itinerary",
    ]

    if any(keyword in normalized_text for keyword in high_value_keywords):
        return 25

    if any(keyword in normalized_text for keyword in medium_value_keywords):
        return 15

    return 5


def calculate_information_completeness_score(company_name: str, message: str) -> int:
    """
    Calculate information completeness score.

    Max score: 15
    - company_name is not empty: +3
    - message length >= 30: +4
    - contains group size signal: +3
    - contains date or month signal: +3
    - contains destination, budget, or itinerary signal: +2
    """
    normalized_message = message.lower()
    score = 0

    if company_name.strip():
        score += 3

    if len(message.strip()) >= 30:
        score += 4

    group_size_keywords = [
        "people",
        "pax",
        "group",
    ]

    date_keywords = [
        "date",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ]

    planning_detail_keywords = [
        "budget",
        "destination",
        "itinerary",
        "private tour",
        "custom tour",
        "china",
        "chengdu",
        "sichuan",
        "tibet",
        "yunnan",
    ]

    if any(keyword in normalized_message for keyword in group_size_keywords):
        score += 3

    if any(keyword in normalized_message for keyword in date_keywords):
        score += 3

    if any(keyword in normalized_message for keyword in planning_detail_keywords):
        score += 2

    return min(score, 15)


def map_score_to_intent_level(lead_score: int) -> str:
    """
    Map final lead score to intent level.

    75-100: High
    45-74: Medium
    0-44: Low
    """
    if lead_score >= 75:
        return "High"

    if lead_score >= 45:
        return "Medium"

    return "Low"


def score_lead(cleaned_lead: CleanedLead) -> LeadScoreResult:
    """
    Score a cleaned lead using rule-based fallback logic.
    """
    text = f"{cleaned_lead.company_name} {cleaned_lead.message}".lower()

    lead_type, lead_subtype = detect_lead_type_and_subtype(text)

    customer_type_score = calculate_customer_type_score(lead_subtype)
    intent_score = calculate_intent_score(text)
    order_value_score = calculate_order_value_score(text)
    information_completeness_score = calculate_information_completeness_score(
        company_name=cleaned_lead.company_name,
        message=cleaned_lead.message,
    )

    lead_score = (
        customer_type_score
        + intent_score
        + order_value_score
        + information_completeness_score
    )
    lead_score = min(lead_score, 100)

    intent_level = map_score_to_intent_level(lead_score)

    return LeadScoreResult(
        lead_type=lead_type,
        lead_subtype=lead_subtype,
        intent_level=intent_level,
        lead_score=lead_score,
    )
