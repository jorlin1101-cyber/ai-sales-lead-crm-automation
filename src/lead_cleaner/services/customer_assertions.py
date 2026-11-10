"""Isolate customer assertions from rejected values and product policy questions."""

import re

from lead_cleaner.services.rule_feature_extractor import extract_group_size

_CLAUSES = re.compile(r"[，,。！？!?；;\n]+|(?<=\.)\s+")
_COUNT = r"(?:\d{1,4}\s*(?:个?\s*[人位]|people\b|persons?\b|pax\b|guests?\b|travel(?:l)?ers?\b)|group of \d{1,4}\b)"
_REJECTED_COUNT = re.compile(rf"(?:不是|并非|不是说|\bnot\s+(?:a\s+)?)\s*{_COUNT}", re.I)
_GROUP_POLICY = re.compile(
    r"起订|起价|起算|起享|折扣|优惠|最低人数|起成团|\b(?:minimum|maximum|discount|threshold|qualify|eligible)\b",
    re.I,
)
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


def customer_group_text(message: str) -> str:
    clauses = _CLAUSES.split(_REJECTED_COUNT.sub("", message))
    return " ".join(
        clause
        for clause in clauses
        if not _GROUP_POLICY.search(clause) or _GROUP_DECLARATION.search(clause)
    )


def group_correction(message: str) -> bool:
    return bool(
        _REJECTED_COUNT.search(message) and extract_group_size(customer_group_text(message))[0]
    )


def travel_days(message: str) -> str | None:
    for clause in _CLAUSES.split(message):
        if _POLICY_PERIOD.search(clause):
            continue
        match = re.search(r"(?<!\d)(\d{1,3})\s*(?:天|[- ]days?\b)", clause, re.I)
        if match and 1 <= int(match[1]) <= 365:
            return match[1]
    return None


def guide_policy_inquiry(clause: str) -> bool:
    return bool(_GUIDE_INQUIRY.search(clause) and not _GUIDE_REQUEST.search(clause))


def slot_has_excluded_evidence(key: str, message: str) -> bool:
    if key == "duration_days":
        return bool(_POLICY_PERIOD.search(message))
    if key == "group_size":
        return bool(_REJECTED_COUNT.search(message) or _GROUP_POLICY.search(message))
    return key == "guide_language" and any(guide_policy_inquiry(c) for c in _CLAUSES.split(message))
