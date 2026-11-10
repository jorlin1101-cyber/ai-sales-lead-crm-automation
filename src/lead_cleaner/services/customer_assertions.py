"""Isolate customer assertions from rejected values and product policy questions."""

import re

from lead_cleaner.services.rule_feature_extractor import extract_group_size

_CLAUSES = re.compile(
    r"[，,。！？!?；;\n]+|(?<=\.)\s+|\s+(?:and|but)\s+(?=we\b|is\b|does\b|what\b|how\b)", re.I
)
_COUNT = r"(?:\d{1,4}\s*(?:个?\s*[人位]|people\b|persons?\b|pax\b|guests?\b|travel(?:l)?ers?\b)|group of \d{1,4}\b)"
_REJECTED_COUNT = re.compile(rf"(?:不是|并非|不是说|\bnot\s+(?:a\s+)?)\s*{_COUNT}", re.I)
_GROUP_POLICY = re.compile(
    r"起订|起价|起算|起享|折扣|优惠|最低人数|起成团|\b(?:minimum|maximum|discount|threshold|qualify|eligible)\b",
    re.I,
)
_CONDITIONAL = re.compile(r"如果|假如|假设|要是|\b(?:if|suppose|assuming)\b", re.I)
_GROUP_DECLARATION = re.compile(
    r"我们(?:一共|有|共|是)?\s*\d|(?:人数|同行)\s*(?:为|是|改为|改成)?\s*\d|"
    r"\b(?:we (?:are|have)|our (?:group|party) (?:of|has)|there are)\s+\d",
    re.I,
)
_POLICY_PERIOD = re.compile(
    r"付款|余款|定金|退款|取消|截止|期限|提前|\b(?:payment|balance|deposit|refund|cancellation|deadline|prior|before)\b",
    re.I,
)
_GUIDE_INQUIRY = re.compile(
    r"包含|包括|提供|是否|可否|有没有|有无|有.{0,12}导游吗|\b(?:included?|includes|available|provided?|offers?)\b",
    re.I,
)
_GUIDE_REQUEST = re.compile(
    r"(?:我们|我)(?:想要|需要|希望|偏好|想请)|(?:请安排|要安排)|"
    r"\b(?:we|I)\s+(?:want|need|prefer|would like)\b",
    re.I,
)
_ASK_ABOUT = re.compile(
    r"请问|想问|咨询|想知道|了解一下|是否|有没有|包括|包含|\b(?:do you offer|is there|do you include|"
    r"is (?:an?|the)\b.*included|know (?:if|whether)|ask (?:if|whether))\b",
    re.I,
)
_TRIP_DECLARATION = re.compile(
    r"(?:我们|我)(?:计划|打算|想|要|准备)|(?:计划|打算|准备)玩|\b(?:we|I)\s+(?:plan|intend|want|need)\b",
    re.I,
)


def customer_clauses(message: str) -> list[str]:
    return _CLAUSES.split(message)


def rejected_group_sizes(message: str) -> set[int | None]:
    return {extract_group_size(match.group())[0] for match in _REJECTED_COUNT.finditer(message)}


def customer_group_text(message: str) -> str:
    clauses = customer_clauses(_REJECTED_COUNT.sub("", message))
    return " ".join(
        clause
        for clause in clauses
        if not _CONDITIONAL.search(clause)
        and (not _GROUP_POLICY.search(clause) or _GROUP_DECLARATION.search(clause))
    )


def group_correction(message: str) -> bool:
    return bool(
        _REJECTED_COUNT.search(message) and extract_group_size(customer_group_text(message))[0]
    )


def travel_days(message: str) -> str | None:
    for clause in customer_clauses(message):
        if _POLICY_PERIOD.search(clause) or (
            _ASK_ABOUT.search(clause) and not _TRIP_DECLARATION.search(clause)
        ):
            continue
        match = re.search(r"(?<!\d)(\d{1,3})\s*(?:天|[- ]days?\b)", clause, re.I)
        if match and 1 <= int(match[1]) <= 365:
            return match[1]
    return None


def guide_policy_inquiry(clause: str) -> bool:
    return bool(
        _GUIDE_INQUIRY.search(clause)
        and (not _GUIDE_REQUEST.search(clause) or _ASK_ABOUT.search(clause))
    )


def slot_has_excluded_evidence(key: str, message: str) -> bool:
    if key == "duration_days":
        return bool(_POLICY_PERIOD.search(message) or _ASK_ABOUT.search(message))
    if key == "group_size":
        return bool(
            _REJECTED_COUNT.search(message)
            or _GROUP_POLICY.search(message)
            or _CONDITIONAL.search(message)
        )
    return key == "guide_language" and any(
        guide_policy_inquiry(c) for c in customer_clauses(message)
    )
