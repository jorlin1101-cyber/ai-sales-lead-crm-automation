"""Product-first sales replies backed by the configured product manuals."""

import re
import hashlib
from collections import defaultdict

from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.conversation import ConversationFact, ProductRecommendation, ReplyDraft
from lead_cleaner.services.conversation_slots import REGIONS, UNRESOLVED
from lead_cleaner.services.knowledge_localization import source_bullets


PRODUCT_NAMES_ZH = {
    "Western Sichuan Private Tour": "川西私人定制游",
    "Yunnan Family Tour": "云南家庭游",
    "Tibet Cultural Tour": "西藏文化游",
}


def _range(text: str, unit: str) -> list[tuple[int, int]]:
    return [
        (int(match[1]), int(match[2] or match[1]))
        for match in re.finditer(rf"(\d+)(?:\s*[–—-]\s*(\d+))?\s*{unit}\b", text, re.I)
    ]


def _duration_options(chunk: RetrievedChunk) -> list[tuple[int, int]]:
    # Minimum durations are customisation bounds, not off-the-shelf itineraries.
    return _range(
        "\n".join(
            line for line in chunk.text.splitlines() if not re.search(r"minimum|custom", line, re.I)
        ),
        "days?",
    )


def recommend_product(
    manuals: list[RetrievedChunk], facts: list[ConversationFact], language: str
) -> tuple[ProductRecommendation | None, list[RetrievedChunk]]:
    known = {fact.key: fact.value for fact in facts if fact.status not in UNRESOLVED}
    region = REGIONS.get(known.get("destination", ""))
    if not region:
        return None, []
    groups: dict[str, list[RetrievedChunk]] = defaultdict(list)
    for chunk in manuals:
        if chunk.doc_type == "product" and chunk.region == region and chunk.product_name:
            groups[chunk.notion_page_id].append(chunk)
    candidates = []
    for sections in groups.values():
        by_section = {chunk.section: chunk for chunk in sections}
        if not {"Suitable For", "Typical Duration"}.issubset(by_section):
            continue
        suitable, duration = by_section["Suitable For"], by_section["Typical Duration"]
        if suitable.product_name != duration.product_name:
            continue
        zh = language == "zh"
        reasons = [
            "目的地与产品手册覆盖地区一致。"
            if zh
            else "The destination matches the product manual."
        ]
        adjustments = []
        constraints = (
            ("group_size", _range(suitable.text, "pax"), "同行人数", "group size"),
            ("duration_days", _duration_options(duration), "天数", "trip duration"),
        )
        matches = 0
        for key, options, label_zh, label_en in constraints:
            value = known.get(key, "")
            if not value.isdigit():
                continue
            if options and any(low <= int(value) <= high for low, high in options):
                matches += 1
                reasons.append(
                    f"{label_zh}：{value}，在手册列出的范围内。"
                    if zh
                    else f"Your {label_en} ({value}) is within a range listed in the manual."
                )
            else:
                adjustments.append(
                    f"您要求的{label_zh}为 {value}，手册未列出完全对应的标准方案，需要另行确认定制安排。"
                    if zh
                    else f"The manual does not list a standard option for your {label_en} ({value}); a custom arrangement needs checking."
                )
        name = suitable.product_name or suitable.source_title
        recommendation = ProductRecommendation(
            product_name=name,
            display_name=PRODUCT_NAMES_ZH.get(name, name) if zh else name,
            fit_status="needs_customization" if adjustments else "candidate",
            reasons=reasons,
            manual_summary=[
                *source_bullets(duration, language)[:2],
                *source_bullets(suitable, language)[:1],
            ],
            adjustments=adjustments,
            source_ids=[duration.chunk_id, suitable.chunk_id],
        )
        candidates.append((len(adjustments), -matches, name, recommendation, [duration, suitable]))
    if not candidates:
        return None, []
    candidates.sort(key=lambda item: item[:3])
    return candidates[0][3], candidates[0][4]


def product_questions(facts: list[ConversationFact], language: str) -> list[str]:
    known = {fact.key for fact in facts if fact.status not in UNRESOLVED}
    fields = [
        ("destination", "目的地", "destination"),
        ("duration_days", "行程天数", "trip duration"),
        ("group_size", "同行人数", "group size"),
    ]
    return [zh if language == "zh" else en for key, zh, en in fields if key not in known]


def product_reply_body(
    product: ProductRecommendation,
    *,
    language: str,
    channel: str,
    questions: list[str],
    extra: str = "",
    pricing: bool = False,
) -> str:
    zh = language == "zh"
    header = (
        f"根据您的需求，建议优先了解「{product.display_name}」。"
        if zh
        else f"Based on your needs, I suggest exploring {product.display_name}."
    )
    if product.adjustments:
        header = (
            f"可以以「{product.display_name}」作为定制参考，以下差异需要调整。"
            if zh
            else f"{product.display_name} is a starting point for a custom trip, subject to the adjustments below."
        )
    parts = [header, ("推荐依据：" if zh else "Why this product: ") + " ".join(product.reasons)]
    parts.append(
        ("手册中的方案：\n" if zh else "Options in the product manual:\n")
        + "\n".join(f"• {line}" for line in product.manual_summary)
    )
    if product.adjustments:
        parts.append(
            ("与您需求的差异：\n" if zh else "Adjustments to your request:\n")
            + "\n".join(f"• {line}" for line in product.adjustments)
        )
    if extra:
        parts.append(extra)
    if pricing:
        parts.append(
            "现有知识库没有适用于所有行程的固定金额。您提供的预算用于筛选方案，不等于产品售价；销售顾问核对资源后将提供明细报价。"
            if zh
            else "There is no universal fixed price in the current manual. Your budget is a selection constraint, not a product price; an itemized quotation requires resource checks."
        )
    parts.append(
        "酒店、用车和导游等已记录偏好将用于定制，具体资源及最终价格仍需核实。"
        if zh
        else "Recorded hotel, vehicle and guide preferences will inform customisation; resource availability and final pricing still need verification."
    )
    visible = questions if channel == "email" else questions[:1]
    if visible:
        parts.append(
            ("为了进一步匹配方案，还想了解：" + "、".join(visible) + "。")
            if zh
            else "To refine the proposal, please share: " + ", ".join(visible) + "."
        )
    if channel == "email":
        parts.insert(0, "您好，" if zh else "Hello,")
        parts.append("祝好\n销售团队" if zh else "Best regards,\nSales Team")
    return "\n\n".join(parts)


def attach_product(
    draft: ReplyDraft, product: ProductRecommendation, language: str, chunks: list[RetrievedChunk]
) -> ReplyDraft:
    extra_chunks = [chunk for chunk in chunks if chunk.chunk_id not in product.source_ids]
    extra = "\n".join(
        line for chunk in extra_chunks for line in source_bullets(chunk, language)[:2]
    )
    body = product_reply_body(
        product,
        language=language,
        channel=draft.channel,
        questions=draft.open_questions,
        extra=extra,
        pricing="pricing" in draft.answer_intents,
    )
    return draft.model_copy(
        update={
            "recommended_products": [product],
            "body_text": body,
            "display_text": body,
            "source_ids": list(
                dict.fromkeys([*product.source_ids, *(c.chunk_id for c in extra_chunks)])
            ),
            "evidence": [
                {
                    "chunk_id": c.chunk_id,
                    "source_title": c.source_title,
                    "section": c.section,
                    "text": c.text,
                    "sha256": hashlib.sha256(c.text.encode()).hexdigest(),
                }
                for c in chunks
            ],
        }
    )
