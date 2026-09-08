from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.conversation import ConversationFact, ConversationMessageRequest
from lead_cleaner.services.knowledge_localization import source_bullets
from lead_cleaner.services.conversation_slots import UNRESOLVED, REGIONS


BusinessIntent = Literal[
    "pricing",
    "permit_payment",
    "itinerary",
    "product_overview",
    "information_collection",
]


@dataclass(frozen=True)
class ConversationKnowledgePlan:
    intents: tuple[BusinessIntent, ...]
    focus_query: str


@dataclass(frozen=True)
class GroundedReplyContent:
    subject: str | None
    body_text: str
    cited_chunk_ids: list[str]
    generation_method: Literal["context_template", "rag_grounded_template"]


_INTENT_PATTERNS: tuple[tuple[BusinessIntent, re.Pattern[str]], ...] = (
    (
        "pricing",
        re.compile(
            r"价格|报价|费用|多少钱|预算|价位|\b(?:prices?|pricing|quotes?|quotation|costs?|rates?)\b",
            re.I,
        ),
    ),
    (
        "permit_payment",
        re.compile(
            r"证件|许可证|许可|签证|付款|支付|定金|尾款|取消|退款|"
            r"permit|visa|payment|deposit|balance|cancel|refund",
            re.I,
        ),
    ),
    (
        "itinerary",
        re.compile(r"路线|行程|几天|时长|天数|怎么玩|itinerary|route|duration|how many days", re.I),
    ),
    (
        "product_overview",
        re.compile(
            r"介绍|产品|适合|亮点|体验|季节|什么时候|推荐|"
            r"product|overview|suitable|experience|season|recommend",
            re.I,
        ),
    ),
)


_FOCUS_QUERIES: dict[BusinessIntent, str] = {
    "pricing": (
        "Private Tour Pricing Rules: Pricing Variables, Group Size, Hotel Level, "
        "Vehicle Type, Seasonal Factors, Quotation Notes"
    ),
    "permit_payment": (
        "Travel Permit and Payment FAQ: Common Questions, Short Answers, Sales Notes"
    ),
    "itinerary": "product itinerary: Typical Duration, Key Experiences, Best Season",
    "product_overview": "product overview: Suitable For, Key Experiences, Typical Duration, Best Season",
    "information_collection": "sales follow-up information required for a tailored proposal",
}


_SECTION_PRIORITY: dict[BusinessIntent, tuple[str, ...]] = {
    "pricing": (
        "Pricing Variables",
        "Group Size",
        "Pricing Notes",
        "Hotel Level",
        "Seasonal Factors",
        "Quotation Notes",
        "Vehicle Type",
        "Guide Requirement",
    ),
    "permit_payment": ("Common Questions", "Short Answers", "Sales Notes", "Risk Notes"),
    "itinerary": ("Typical Duration", "Key Experiences", "Best Season", "Travel Style"),
    "product_overview": (
        "Key Experiences",
        "Typical Duration",
        "Suitable For",
        "Best Season",
        "Region Overview",
    ),
    "information_collection": ("Sales Follow-up Notes", "Quotation Notes", "Sales Notes"),
}


def build_knowledge_plan(message: str) -> ConversationKnowledgePlan:
    intents = tuple(intent for intent, pattern in _INTENT_PATTERNS if pattern.search(message))
    if not intents:
        intents = ("information_collection",)
    focus_query = " | ".join(_FOCUS_QUERIES[intent] for intent in intents)
    return ConversationKnowledgePlan(intents=intents, focus_query=focus_query)


def _section_index(intent: BusinessIntent, section: str) -> int | None:
    sections = _SECTION_PRIORITY[intent]
    try:
        return sections.index(section)
    except ValueError:
        return None


def _eligible_for_language(chunk: RetrievedChunk, language: str) -> bool:
    return bool(chunk.text.strip())


def select_grounding_chunks(
    chunks: list[RetrievedChunk],
    plan: ConversationKnowledgePlan,
    *,
    language: str,
    limit: int = 3,
    destination: str | None = None,
) -> list[RetrievedChunk]:
    """Select a small evidence set that covers each detected business intent."""

    # Apply business scope before ranking. Unknown destinations may only use general rules.
    region = REGIONS.get(destination or "")
    unique = {
        chunk.chunk_id: chunk
        for chunk in chunks
        if not destination or chunk.region == "general" or chunk.region == region
    }
    selected: list[RetrievedChunk] = []
    selected_ids: set[str] = set()

    def candidates(intent: BusinessIntent) -> list[RetrievedChunk]:
        ranked: list[tuple[int, int, float, RetrievedChunk]] = []
        for chunk in unique.values():
            index = _section_index(intent, chunk.section)
            if not _eligible_for_language(chunk, language):
                continue
            if index is None:
                index = 100
            ranked.append((index, chunk.rank, -chunk.score, chunk))
        return [item[-1] for item in sorted(ranked, key=lambda item: item[:3])]

    for intent in plan.intents:
        for chunk in candidates(intent):
            if chunk.chunk_id not in selected_ids:
                selected.append(chunk)
                selected_ids.add(chunk.chunk_id)
                break
        if len(selected) == limit:
            return selected

    for intent in plan.intents:
        for chunk in candidates(intent):
            if chunk.chunk_id in selected_ids:
                continue
            selected.append(chunk)
            selected_ids.add(chunk.chunk_id)
            if len(selected) == limit:
                return selected
    return selected


def _english_bullets(chunk: RetrievedChunk) -> list[str]:
    bullets = []
    for line in chunk.text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
    return bullets[:2]


def _knowledge_bullets(chunk: RetrievedChunk, language: str) -> list[str]:
    return source_bullets(chunk, language)


def _fact_text(facts: list[ConversationFact], language: str) -> str:
    labels = {
        "group_size": ("同行人数", "group size"),
        "destination": ("目的地", "destination"),
        "travel_date": ("出行日期", "travel dates"),
        "duration_days": ("行程天数", "trip duration"),
        "budget": ("预算", "budget"),
        "hotel_tier": ("酒店等级", "hotel tier"),
        "vehicle": ("用车需求", "vehicle"),
        "guide_language": ("导游语言", "guide language"),
        "special_requirements": ("特殊需求", "special requirements"),
    }
    zh_values = {"Western Sichuan": "川西", "Sichuan": "四川", "Tibet": "西藏", "Yunnan": "云南"}
    visible = [fact for fact in facts if fact.status not in UNRESOLVED]
    separator = "；" if language == "zh" else "; "
    label_index = 0 if language == "zh" else 1
    return separator.join(
        f"{labels.get(fact.key, (fact.key, fact.key))[label_index]}：{zh_values.get(fact.value, fact.value)}"
        if language == "zh"
        else f"{labels.get(fact.key, (fact.key, fact.key))[label_index]}: {fact.value}"
        for fact in visible
    )


def _missing_quote_details(facts: list[ConversationFact], language: str) -> list[str]:
    keys = {fact.key for fact in facts if fact.status != "conflicted"}
    fields: list[tuple[str, str, str]] = [
        ("destination", "目的地和希望覆盖的线路", "destination and preferred route"),
        ("group_size", "成人与儿童人数", "number of adults and children"),
        ("travel_date", "出发日期和行程天数", "travel dates and trip duration"),
        ("hotel_tier", "酒店等级", "hotel tier"),
        ("vehicle", "用车需求", "vehicle requirements"),
        ("guide_language", "导游语言", "guide language"),
    ]
    missing = [zh if language == "zh" else en for key, zh, en in fields if key not in keys]
    return missing


def compose_grounded_reply(
    request: ConversationMessageRequest,
    *,
    facts: list[ConversationFact],
    open_questions: list[str],
    plan: ConversationKnowledgePlan,
    chunks: list[RetrievedChunk],
    language: str | None = None,
) -> GroundedReplyContent:
    language = language or ("zh" if re.search(r"[\u4e00-\u9fff]", request.message) else "en")
    evidence_lines: list[tuple[str, str]] = []
    for chunk in chunks:
        for bullet in _knowledge_bullets(chunk, language):
            evidence_lines.append((chunk.chunk_id, bullet))
    if not evidence_lines:
        return _compose_context_reply(
            request, facts=facts, open_questions=open_questions, language=language
        )

    bullet_limit = 4 if request.channel == "email" else 3
    bullet_text = evidence_lines[:bullet_limit]
    cited_ids = list(dict.fromkeys(chunk_id for chunk_id, _ in bullet_text))[:3]
    fact_text = _fact_text(facts, language)
    pricing = "pricing" in plan.intents
    if language == "zh":
        intro = "您好，关于您的问题，根据当前产品与服务资料："
        details = "\n".join(f"• {line}" for _, line in bullet_text)
        pricing_note = ""
        follow_up = ""
        if pricing:
            missing = "、".join(
                open_questions if request.channel == "email" else open_questions[:1]
            )
            pricing_note = (
                "\n\n现有知识库没有适用于所有行程的固定金额。本回复不构成正式报价；"
                "具体金额需要依据有效报价规则按实际服务组合核算，"
                "销售顾问核对资源后将提供明细报价。"
            )
            follow_up = f"\n为生成正式报价，请再确认：{missing}。" if missing else ""
        elif open_questions:
            questions = "、".join(
                open_questions if request.channel == "email" else open_questions[:1]
            )
            follow_up = f"\n如需继续定制，请再补充：{questions}。"
        context = f"\n目前已记录：{fact_text}。" if fact_text else ""
        close = "\n以上方案及价格在发送或预订前仍会由销售顾问复核。"
        core = f"{intro}\n{details}{pricing_note}{context}{follow_up}{close}"
        subject = (
            f"Re: {request.subject}"
            if request.channel == "email" and request.subject
            else ("您的行程咨询与下一步信息确认" if request.channel == "email" else None)
        )
        body = f"{core}\n\n祝好\n销售团队" if request.channel == "email" else core
    else:
        intro = "Hello, based on the current product and service information:"
        details = "\n".join(f"• {line}" for _, line in bullet_text)
        pricing_note = ""
        follow_up = ""
        if pricing:
            missing = ", ".join(
                open_questions if request.channel == "email" else open_questions[:1]
            )
            pricing_note = (
                "\n\nThis reply is not a formal quotation. A verified quotation depends "
                "on the selected services. A sales specialist will verify an itemized quotation."
            )
            follow_up = (
                f"\nTo prepare a formal quotation, please confirm: {missing}." if missing else ""
            )
        elif open_questions:
            questions = ", ".join(
                open_questions if request.channel == "email" else open_questions[:1]
            )
            follow_up = f"\nTo continue tailoring the trip, please confirm: {questions}."
        context = f"\nWe have noted: {fact_text}." if fact_text else ""
        close = (
            "\nA sales specialist will review the itinerary and price before it is sent or booked."
        )
        core = f"{intro}\n{details}{pricing_note}{context}{follow_up}{close}"
        subject = (
            f"Re: {request.subject}"
            if request.channel == "email" and request.subject
            else ("Your trip inquiry and next details" if request.channel == "email" else None)
        )
        body = f"{core}\n\nBest regards,\nSales Team" if request.channel == "email" else core

    return GroundedReplyContent(
        subject=subject,
        body_text=body,
        cited_chunk_ids=cited_ids,
        generation_method="rag_grounded_template",
    )


def _compose_context_reply(
    request: ConversationMessageRequest,
    *,
    facts: list[ConversationFact],
    open_questions: list[str],
    language: str,
) -> GroundedReplyContent:
    fact_text = _fact_text(facts, language)
    visible = open_questions if request.channel == "email" else open_questions[:1]
    if language == "zh":
        context = f"目前已记录：{fact_text}。" if fact_text else ""
        ask = (
            f"为便于继续准备方案，请补充：{'、'.join(visible)}。"
            if visible
            else "信息已基本齐全，销售顾问将继续核对资源与报价。"
        )
        subject = (
            f"Re: {request.subject}"
            if request.channel == "email" and request.subject
            else ("进一步确认您的行程需求" if request.channel == "email" else None)
        )
        core = f"您好，感谢您的回复。{context}{ask}"
        body = f"{core}\n\n祝好\n销售团队" if request.channel == "email" else core
    else:
        context = f"We have noted: {fact_text}. " if fact_text else ""
        ask = (
            f"Please also confirm: {', '.join(visible)}."
            if visible
            else "The key details are complete. A sales specialist will verify resources and pricing."
        )
        subject = (
            f"Re: {request.subject}"
            if request.channel == "email" and request.subject
            else ("A few details about your travel inquiry" if request.channel == "email" else None)
        )
        core = f"Hello, thank you for your reply. {context}{ask}"
        body = f"{core}\n\nBest regards,\nSales Team" if request.channel == "email" else core
    return GroundedReplyContent(
        subject=subject,
        body_text=body,
        cited_chunk_ids=[],
        generation_method="context_template",
    )
