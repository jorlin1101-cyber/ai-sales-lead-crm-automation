"""Explicit service preferences, including labelled answers and negative choices."""

import re

from lead_cleaner.schemas.conversation import ConversationFact

FLEXIBLE = "不限（由顾问推荐）"
LABELS = {
    "hotel_tier": r"酒店(?:等级|星级|标准)?|住宿(?:等级|标准)?|hotel(?:\s+tier|\s+rating)?",
    "vehicle": r"用车(?:需求)?|车型|车辆(?:要求|需求)?|vehicle(?:\s+requirements)?",
    "guide_language": r"导游(?:语言|语种)?|讲解语言|guide(?:\s+language)?",
}
UNKNOWN = re.compile(r"还没|未定|待定|不确定|没想好|不知道|not sure|undecided|tbd", re.I)
ANY = re.compile(r"都可以|均可|不限|无要求|没要求|没有要求|随意|随便|any|no preference", re.I)
STAR = re.compile(
    r"([一二三四五12345])\s*(?:星(?:级)?|[- ]?stars?)|\b(one|two|three|four|five)[- ]star", re.I
)


def normalize_preference(key: str, value: str) -> str:
    if key == "hotel_tier":
        match = STAR.fullmatch(value.strip())
        if match:
            number = match.group(1) or match.group(2).lower()
            number = {
                "一": "1",
                "二": "2",
                "三": "3",
                "四": "4",
                "五": "5",
                "one": "1",
                "two": "2",
                "three": "3",
                "four": "4",
                "five": "5",
            }.get(number, number)
            return f"{number}星级"
    if key == "guide_language":
        if re.fullmatch(r"(?:中文|汉语|普通话|Chinese|Mandarin)(?:导游|\s+guide)?", value, re.I):
            return "中文"
        if re.fullmatch(r"(?:英文|英语|English)(?:导游|\s+guide)?", value, re.I):
            return "英语"
    return value.strip()


def extract_preferences(message: str, message_id: str) -> list[ConversationFact]:
    values: dict[str, str] = {}
    for clause in re.split(r"[，,。；;\n]+", message):
        if UNKNOWN.search(clause):
            continue
        labelled = {key: re.search(label, clause, re.I) for key, label in LABELS.items()}
        for key, label in labelled.items():
            if label and ANY.search(clause[label.end() :]):
                values[key] = FLEXIBLE
        # Prefer the positive replacement in “不是五星，是四星”, never the rejected value.
        positive_clause = re.sub(
            r"(?:不要|不选|不是|not\s+)\s*(?:[一二三四五12345]\s*星(?:级)?|[1-5][- ]star)",
            "",
            clause,
            flags=re.I,
        )
        hotel = STAR.search(positive_clause)
        if re.search(r"(?:不需要|不用|无需)(?:安排)?(?:酒店|住宿)|no hotel", clause, re.I):
            values["hotel_tier"] = "无需安排住宿"
        elif hotel:
            values["hotel_tier"] = normalize_preference("hotel_tier", hotel.group())
        else:
            match = re.search(
                r"舒适型|品质型|豪华型|经济型|民宿|comfort|premium|luxury", clause, re.I
            )
            if match:
                values["hotel_tier"] = match.group()
        if re.search(
            r"(?:不再需要|不需要|不用|无需)(?:安排)?(?:用车|车辆|车|包车)|no (?:vehicle|car)",
            clause,
            re.I,
        ):
            values["vehicle"] = "不需要用车"
        else:
            match = re.search(
                r"(?:\d+\s*座\s*)?(?:商务车|商务|轿车|中巴|大巴|SUV|MPV)|\d+\s*座(?:车)?|自驾|包车|private car",
                clause,
                re.I,
            )
            if match and not re.search(r"不要|不选|不是|not\s*$", clause[: match.start()], re.I):
                values["vehicle"] = match.group().strip()
            elif match:
                values["vehicle"] = "排除：" + match.group().strip() + "；具体需求待定"
            elif re.search(
                r"(?:需要|要)(?:安排|一辆)?(?:用车|车辆|车)|need (?:a )?(?:car|vehicle)",
                clause,
                re.I,
            ):
                values["vehicle"] = "需要用车（车型由顾问安排）"
        if re.search(r"(?:不再需要|不需要|不用|无需)(?:安排)?导游|no guide", clause, re.I):
            values["guide_language"] = "不需要导游"
        elif labelled["guide_language"]:
            match = re.search(
                r"中文|汉语|普通话|英文|英语|日语|韩语|法语|德语|西班牙语|Chinese|Mandarin|English|Japanese|Korean|French|German|Spanish",
                clause,
                re.I,
            )
            if match and not re.search(r"不要|不选|不是|not\s*$", clause[: match.start()], re.I):
                values["guide_language"] = normalize_preference("guide_language", match.group())
            elif match:
                values["guide_language"] = "排除：" + match.group() + "；具体需求待定"
    return [
        ConversationFact(
            key=key,
            value=value,
            status="pending" if value.startswith("排除：") else "customer_confirmed",
            confidence=0.9,
            source_message_id=message_id,
        )
        for key, value in values.items()
    ]
