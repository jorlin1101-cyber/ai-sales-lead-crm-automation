import re

from lead_cleaner.rag.schemas import RetrievalIntent, RetrievalTopic
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import LeadFeatures


EMAIL_PATTERN = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", re.IGNORECASE)
URL_PATTERN = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")
WHITESPACE_PATTERN = re.compile(r"\s+")

TOPIC_KEYWORDS: dict[RetrievalTopic, tuple[str, ...]] = {
    "payment_policy": (
        "deposit",
        "final balance",
        "remaining balance",
        "pay everything",
        "pay in full",
        "payment",
        "付款",
        "定金",
        "尾款",
        "全款",
    ),
    "travel_permit": (
        "permit",
        "travel document",
        "entry requirement",
        "visa",
        "许可证",
        "入藏函",
        "入境要求",
        "签证",
    ),
    "family_travel": (
        "family",
        "families",
        "children",
        "child",
        "kids",
        "kid",
        "亲子",
        "家庭",
        "小朋友",
        "孩子",
    ),
    "cultural_experience": (
        "culture",
        "cultural",
        "meaningful journey",
        "monastery",
        "local experience",
        "local experiences",
        "文化",
        "寺院",
        "当地体验",
        "深度体验",
    ),
    "trip_duration": (
        "how many days",
        "number of days",
        "trip duration",
        "tour duration",
        "itinerary length",
        "几天",
        "多少天",
        "行程时长",
        "行程多久",
    ),
    "flexible_pacing": (
        "not too rushed",
        "flexible pacing",
        "flexible pace",
        "slow pace",
        "relaxed pace",
        "不想行程太赶",
        "行程太赶",
        "灵活节奏",
        "轻松节奏",
    ),
    "private_custom": (
        "private travel",
        "private journey",
        "private tour",
        "private trip",
        "customized trip",
        "customised trip",
        "custom tour",
        "私人旅行",
        "私人行程",
        "私人定制",
        "定制行程",
    ),
}

TOPIC_QUERY_TERMS: dict[RetrievalTopic, str] = {
    "pricing": "pricing quotation cost factors",
    "payment_policy": "payment policy deposit final balance",
    "travel_permit": "travel permit entry requirements foreign travelers",
    "family_travel": "family children suitable tour",
    "cultural_experience": "cultural journey local experiences",
    "trip_duration": "typical trip duration number of days",
    "flexible_pacing": "flexible pacing not rushed",
    "private_custom": "private custom tour",
    "availability": "availability booking",
    "partnership": "travel partnership",
}

CUSTOMER_KIND_QUERY_TERMS = {
    "agency": "travel agency",
    "operator": "tour operator",
    "school": "school group",
    "corporate": "corporate group",
    "influencer": "travel influencer",
    "individual": "individual traveler",
    "unknown": "traveler",
}


def sanitize_original_retrieval_query(message: str) -> str:
    """Remove obvious contact data while preserving the user's wording."""

    sanitized = EMAIL_PATTERN.sub(" ", message)
    sanitized = URL_PATTERN.sub(" ", sanitized)
    sanitized = PHONE_PATTERN.sub(" ", sanitized)
    return WHITESPACE_PATTERN.sub(" ", sanitized).strip()


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def build_retrieval_intent(
    cleaned_lead: CleanedLead,
    features: LeadFeatures,
) -> RetrievalIntent:
    """Add retrieval topics that do not belong in the scoring feature contract."""

    normalized_message = cleaned_lead.message.lower()
    topic_codes: list[RetrievalTopic] = []

    if features.asks_for_price:
        topic_codes.append("pricing")

    for topic_code, keywords in TOPIC_KEYWORDS.items():
        if _contains_any(normalized_message, keywords):
            topic_codes.append(topic_code)

    if features.requests_private_or_custom_service:
        topic_codes.append("private_custom")
    if features.asks_for_availability:
        topic_codes.append("availability")
    if features.requests_partnership:
        topic_codes.append("partnership")

    return RetrievalIntent(
        customer_kind=features.customer_kind,
        destinations=features.destinations,
        group_size=features.group_size,
        topic_codes=list(dict.fromkeys(topic_codes)),
        language=features.language,
    )


def build_retrieval_intent_query(intent: RetrievalIntent) -> str:
    """Serialize a RetrievalIntent into stable English knowledge-base terms."""

    parts = [CUSTOMER_KIND_QUERY_TERMS[intent.customer_kind]]

    destinations = list(
        dict.fromkeys(
            destination.strip() for destination in intent.destinations if destination.strip()
        )
    )
    if destinations:
        parts.append(f"destinations {' '.join(destinations)}")

    if intent.group_size is not None:
        parts.append(f"group size {intent.group_size} people")

    parts.extend(TOPIC_QUERY_TERMS[topic_code] for topic_code in intent.topic_codes)

    if len(parts) == 1 and intent.customer_kind == "unknown":
        parts.append("general travel product information")

    return " | ".join(parts)


def build_retrieval_queries(
    cleaned_lead: CleanedLead,
    features: LeadFeatures,
) -> list[str]:
    """Return distinct original and structured queries in a stable order."""

    intent = build_retrieval_intent(cleaned_lead, features)
    candidates = [
        sanitize_original_retrieval_query(cleaned_lead.message),
        build_retrieval_intent_query(intent),
    ]
    return list(dict.fromkeys(query for query in candidates if query))
