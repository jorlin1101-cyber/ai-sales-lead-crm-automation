"""Shared slot validation and missing-information policy, independent of any model."""

import re
from datetime import date
from typing import Literal

from lead_cleaner.schemas.conversation import ConversationFact
from lead_cleaner.services.service_preferences import LABELS, UNKNOWN, normalize_preference

FACT_LABELS = {
    "destination": ("目的地", "destination"),
    "group_size": ("同行人数", "group size"),
    "travel_date": ("出行日期", "travel dates"),
    "duration_days": ("行程天数", "trip duration"),
    "budget": ("预算范围", "budget range"),
    "hotel_tier": ("酒店等级", "hotel tier"),
    "vehicle": ("用车需求", "vehicle requirements"),
    "guide_language": ("导游语言", "guide language"),
    "special_requirements": ("特殊需求", "special requirements"),
}
UNRESOLVED = {"conflicted", "pending"}
REGIONS = {
    "Western Sichuan": "western_sichuan",
    "Sichuan": "western_sichuan",
    "Chengdu": "western_sichuan",
    "Tibet": "tibet",
    "Yunnan": "yunnan",
    "川西": "western_sichuan",
    "四川": "western_sichuan",
    "成都": "western_sichuan",
    "西藏": "tibet",
    "云南": "yunnan",
}
DESTINATIONS = {
    "Western Sichuan": r"川西|western sichuan",
    "Sichuan": r"四川|(?<!western )\bsichuan\b",
    "Yunnan": r"云南|\byunnan\b",
    "Tibet": r"西藏|\btibet\b",
    "Chengdu": r"成都|\bchengdu\b",
}


def fact(key: str, value: str, message_id: str, *, pending: bool = False) -> ConversationFact:
    return ConversationFact(
        key=key,
        value=value[:500],
        status="pending" if pending else "customer_confirmed",
        confidence=0.9,
        source_message_id=message_id,
    )


def valid_date(value: str) -> bool:
    match = re.search(r"(?:(20\d{2})[年/-])?(\d{1,2})[月/-](\d{1,2})", value)
    if not match:
        return False
    try:
        # Leap-year sentinel validates month/day without inventing a customer year.
        start = date(int(match[1] or 2000), int(match[2]), int(match[3]))
        tail = value[match.end() :].strip("日号 ")
        if tail:
            end = re.fullmatch(
                r"(?:到|至|[-–])\s*(?:(20\d{2})[年/-])?(?:(\d{1,2})[月/-])?(\d{1,2})[日号]?", tail
            )
            if not end:
                return False
            finish = date(int(end[1] or start.year), int(end[2] or start.month), int(end[3]))
            if finish < start:
                return False
        return True
    except ValueError:
        return False


def equivalent_budget(a: str, b: str) -> bool:
    def normalized(value: str):
        amount = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(万|千|k)?", value, re.I)
        if not amount:
            return None
        number = float(amount[1].replace(",", "")) * {"万": 10000, "千": 1000, "k": 1000}.get(
            (amount[2] or "").lower(), 1
        )
        currency = "USD" if re.search(r"USD|美元|\$", value, re.I) else "CNY"
        scope = (
            "person"
            if re.search(r"人均|每人|per\s*person", value, re.I)
            else "total"
            if re.search(r"总|total", value, re.I)
            else "unspecified"
        )
        return number, currency, scope

    left, right = normalized(a), normalized(b)
    return left is not None and left == right


def validate_slot(key: str, value: str) -> bool:
    if key not in FACT_LABELS or not value.strip():
        return False
    if key == "travel_date":
        return valid_date(value)
    if key in {"group_size", "duration_days"}:
        return value.isdigit() and 1 <= int(value) <= (365 if key == "duration_days" else 10000)
    return True


def enrich_facts(
    message: str, message_id: str, incoming: list[ConversationFact], previous_questions: list[str]
) -> list[ConversationFact]:
    values = {f.key: f for f in incoming}
    if "travel_date" in values and not valid_date(values["travel_date"].value):
        values["travel_date"] = fact(
            "travel_date", "日期无效，请重新确认", message_id, pending=True
        )
    # A mention inside a rejected clause is never a confirmed destination.
    destinations = []
    for clause in re.split(r"[，,。；;\n]+", message):
        for name, pattern in DESTINATIONS.items():
            for match in re.finditer(pattern, clause, re.I):
                before = clause[: match.start()]
                if not re.search(r"(?:不去|不考虑|不要去|not going|instead of)\s*$", before, re.I):
                    destinations.append(name)
    if destinations:
        values["destination"] = fact("destination", destinations[-1], message_id)
    elif "destination" in values:
        values.pop("destination")
    other_destination = re.search(
        r"(?:改去|目的地[：:是])\s*([\u4e00-\u9fff]{2,12})(?=[，,。；;\s]|$)", message
    )
    if other_destination and not destinations:
        values["destination"] = fact("destination", other_destination[1], message_id)
    duration = re.search(
        r"(?:一共|行程|玩|去|共|总共)?\s*(\d+)\s*天|\b(\d+)[- ]days?\b", message, re.I
    )
    if duration and 1 <= int(duration[1] or duration[2]) <= 365:
        values["duration_days"] = fact("duration_days", duration[1] or duration[2], message_id)
    for clause in re.split(r"[，,。；;\n]+", message):
        for key, label in {
            **LABELS,
            "travel_date": r"日期|date",
            "budget": r"预算|budget",
            "destination": r"目的地|destination",
        }.items():
            if re.search(label, clause, re.I) and UNKNOWN.search(clause):
                values[key] = fact(key, "待定", message_id, pending=True)
        if re.search(
            r"无障碍|轮椅|过敏|素食|忌口|儿童座椅|行动不便|wheelchair|allerg|vegetarian|accessible|child seat",
            clause,
            re.I,
        ):
            values["special_requirements"] = fact(
                "special_requirements", clause.strip(), message_id
            )
    # A short language answer is safe only when guide language was actually asked.
    if re.fullmatch(
        r"\s*(?:中文|汉语|普通话|英语|英文|English|Chinese|Mandarin)[。.!！\s]*", message, re.I
    ):
        values["guide_language"] = fact(
            "guide_language",
            normalize_preference("guide_language", message.strip("。.!！ ")),
            message_id,
        )
    return list(values.values())


def missing_fields(facts: list[ConversationFact], *, pricing: bool, language: str) -> list[str]:
    known = {f.key for f in facts if f.status not in UNRESOLVED}
    # Quotation can proceed with these mandatory inputs. Duration, vehicle and guide
    # remain useful optional facts, but must not keep a complete customer in a loop.
    required = (
        ["destination", "group_size", "travel_date", "hotel_tier"]
        if pricing
        else ["travel_date", "group_size", "budget", "special_requirements"]
    )
    # A complete range also supplies duration; a single date does not.
    if any(
        f.key == "travel_date" and f.status not in UNRESOLVED and re.search(r"到|至|–", f.value)
        for f in facts
    ):
        known.add("duration_days")
    return [FACT_LABELS[key][0 if language == "zh" else 1] for key in required if key not in known]


def conversation_language(
    message: str, previous: Literal["zh", "en"] = "zh"
) -> Literal["zh", "en"]:
    if re.search(r"(?:用|请|改成|reply in|respond in)\s*(?:英语|英文|English)", message, re.I):
        return "en"
    if re.search(r"(?:用|请|改成|reply in|respond in)\s*(?:中文|汉语|Chinese)", message, re.I):
        return "zh"
    if re.search(r"[\u4e00-\u9fff]", message):
        return "zh"
    if len(message.strip()) < 15:
        return previous
    return "en"
