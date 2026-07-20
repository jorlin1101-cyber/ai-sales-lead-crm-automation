import re

from lead_cleaner.config import AppMode
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import CustomerKind, LeadFeatures
from lead_cleaner.services.feature_extractor import (
    FallbackReason,
    FeatureExtractionOutcome,
)


CUSTOMER_KIND_KEYWORDS: dict[CustomerKind, tuple[str, ...]] = {
    "agency": (
        "travel agency",
        "旅行社",
        "旅游代理",
    ),
    "operator": (
        "tour operator",
        "地接社",
        "旅行运营商",
    ),
    "school": (
        "school",
        "university",
        "student group",
        "学校",
        "大学",
        "学生团",
    ),
    "corporate": (
        "corporate",
        "company retreat",
        "incentive trip",
        "business meeting",
        "conference group",
        "企业团",
        "公司团建",
        "商务团",
        "奖励旅游",
    ),
    "influencer": (
        "influencer",
        "blogger",
        "content creator",
        "media creator",
        "博主",
        "网红",
        "自媒体",
        "内容创作者",
    ),
    "individual": (),
    "unknown": (),
}

B2B_CUSTOMER_KINDS: tuple[CustomerKind, ...] = (
    "agency",
    "operator",
    "school",
    "corporate",
    "influencer",
)

INDIVIDUAL_KEYWORDS = (
    "solo traveler",
    "independent traveler",
    "couple",
    "my wife",
    "my husband",
    "my parents",
    "my family",
    "my girlfriend",
    "my boyfriend",
    "个人旅行",
    "独自旅行",
    "自由行",
    "情侣",
    "夫妻",
    "家人",
    "家庭旅行",
)

PRICE_KEYWORDS = (
    "quotation",
    "quote",
    "pricing",
    "price",
    "how much",
    "cost",
    "报价",
    "价格",
    "费用",
    "多少钱",
)

AVAILABILITY_KEYWORDS = (
    "availability",
    "available",
    "open slots",
    "can you accommodate",
    "档期",
    "是否有空",
    "可以预订",
    "能否安排",
)

PRIVATE_CUSTOM_KEYWORDS = (
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
    "私人团",
    "私家团",
    "私人服务",
    "定制团",
    "定制行程",
    "私人导游",
    "包车",
)

PARTNERSHIP_KEYWORDS = (
    "partnership",
    "business cooperation",
    "long-term cooperation",
    "work together",
    "合作",
    "长期合作",
    "商务合作",
    "渠道合作",
)

SPAM_KEYWORDS = (
    "seo service",
    "backlink service",
    "guest post service",
    "buy followers",
    "promote your website",
    "casino promotion",
    "crypto investment",
    "网站推广",
    "代运营推广",
    "购买粉丝",
    "博彩推广",
    "加密货币投资",
)

DESTINATION_ALIASES: dict[str, tuple[str, ...]] = {
    "China": ("china", "中国"),
    "Chengdu": ("chengdu", "成都"),
    "Sichuan": ("sichuan", "四川"),
    "Western Sichuan": ("western sichuan", "west sichuan", "川西"),
    "Tibet": ("tibet", "西藏"),
    "Yunnan": ("yunnan", "云南"),
    "Jiuzhaigou": ("jiuzhaigou", "九寨沟"),
    "Beijing": ("beijing", "北京"),
    "Shanghai": ("shanghai", "上海"),
    "Xi'an": ("xi'an", "xian", "西安"),
}

GROUP_SIZE_PATTERNS = (
    re.compile(r"\bgroup\s+of\s+(\d{1,4})\b", re.IGNORECASE),
    re.compile(
        r"\b(\d{1,4})\s*(?:people|persons|pax|travellers?|travelers?|guests?|clients?|students?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(\d{1,4})\s*(?:人|位)(?:游客|客人|学生)?"),
)

DATE_PATTERNS = (
    re.compile(
        r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bnext\s+(?:week|month|year)\b", re.IGNORECASE),
    re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"),
    re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b"),
    re.compile(r"\d{1,2}月(?:\d{1,2}[日号])?"),
    re.compile(r"(?:下周|下个月|明年|具体日期|出发日期)"),
)

PRIVATE_CUSTOM_PATTERN = re.compile(
    r"\bprivate\b.{0,40}\b(?:tour|trip|itinerary|service|guide|driver)\b",
    re.IGNORECASE,
)


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def extract_group_size(message: str) -> tuple[int | None, list[str]]:
    matches: set[int] = set()
    for pattern in GROUP_SIZE_PATTERNS:
        matches.update(int(value) for value in pattern.findall(message))

    valid_matches = {value for value in matches if 1 <= value <= 10000}
    if len(valid_matches) == 1:
        return valid_matches.pop(), []
    if len(valid_matches) > 1:
        return None, ["conflicting_group_sizes"]
    return None, []


def detect_customer_kind(
    text: str,
    *,
    group_size: int | None,
    requests_private_or_custom_service: bool,
    destinations: list[str],
) -> tuple[CustomerKind, list[str]]:
    matched_b2b_kinds: list[CustomerKind] = [
        customer_kind
        for customer_kind in B2B_CUSTOMER_KINDS
        if contains_any(text, CUSTOMER_KIND_KEYWORDS[customer_kind])
    ]

    conflict_codes: list[str] = []
    if len(matched_b2b_kinds) > 1:
        conflict_codes.append("multiple_customer_kinds")

    if matched_b2b_kinds:
        return matched_b2b_kinds[0], conflict_codes

    has_individual_evidence = (
        contains_any(text, INDIVIDUAL_KEYWORDS)
        or group_size is not None
        or requests_private_or_custom_service
        or bool(destinations)
    )
    if has_individual_evidence:
        return "individual", conflict_codes

    return "unknown", conflict_codes


def detect_destinations(text: str) -> list[str]:
    return [
        destination
        for destination, aliases in DESTINATION_ALIASES.items()
        if contains_any(text, aliases)
    ]


def detect_language(message: str) -> str:
    if re.search(r"[\u3400-\u9fff]", message):
        return "zh"
    if re.search(r"[a-z]", message, re.IGNORECASE):
        return "en"
    return "unknown"


def mentions_specific_dates(message: str) -> bool:
    return any(pattern.search(message) is not None for pattern in DATE_PATTERNS)


def extract_rule_features(cleaned_lead: CleanedLead) -> LeadFeatures:
    normalized_message = cleaned_lead.message.lower()
    normalized_text = f"{cleaned_lead.company_name} {cleaned_lead.message}".lower()

    group_size, group_conflict_codes = extract_group_size(normalized_message)
    destinations = detect_destinations(normalized_message)
    requests_private_or_custom_service = (
        contains_any(normalized_message, PRIVATE_CUSTOM_KEYWORDS)
        or PRIVATE_CUSTOM_PATTERN.search(normalized_message) is not None
    )
    customer_kind, customer_conflict_codes = detect_customer_kind(
        normalized_text,
        group_size=group_size,
        requests_private_or_custom_service=requests_private_or_custom_service,
        destinations=destinations,
    )

    return LeadFeatures(
        customer_kind=customer_kind,
        group_size=group_size,
        mentions_specific_dates=mentions_specific_dates(normalized_message),
        asks_for_price=contains_any(normalized_message, PRICE_KEYWORDS),
        asks_for_availability=contains_any(normalized_message, AVAILABILITY_KEYWORDS),
        requests_private_or_custom_service=requests_private_or_custom_service,
        requests_partnership=contains_any(normalized_message, PARTNERSHIP_KEYWORDS),
        contains_spam_or_promotion=contains_any(normalized_message, SPAM_KEYWORDS),
        destinations=destinations,
        language=detect_language(cleaned_lead.message),
        company_name_present=bool(cleaned_lead.company_name.strip()),
        cleaned_message_length=len(cleaned_lead.message.strip()),
        conflict_codes=group_conflict_codes + customer_conflict_codes,
    )


class RuleFeatureExtractor:
    """FeatureExtractor implementation backed by deterministic local rules."""

    def __init__(
        self,
        *,
        execution_mode: AppMode = AppMode.RULE_ONLY,
        fallback_reason: FallbackReason | None = None,
    ) -> None:
        self._execution_mode = execution_mode
        self._fallback_reason = fallback_reason

    def extract(
        self,
        cleaned_lead: CleanedLead,
    ) -> FeatureExtractionOutcome:
        features = extract_rule_features(cleaned_lead)

        return FeatureExtractionOutcome(
            features=features,
            execution_mode=self._execution_mode,
            analysis_method="rule_features",
            fallback_reason=self._fallback_reason,
        )
