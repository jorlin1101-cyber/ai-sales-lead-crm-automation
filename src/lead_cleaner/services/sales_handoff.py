"""Decide which handbook claims require an order, supplier or policy check."""

from __future__ import annotations

import calendar
import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.conversation import ConversationFact, ReplyDraft
from lead_cleaner.services.conversation_slots import REGIONS, UNRESOLVED
from lead_cleaner.services.inquiry_evidence import (
    Topic,
    display_quote,
    find_points,
    point_chunks,
    point_guidance,
)


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


@dataclass
class SalesReview:
    notes: list[str] = field(default_factory=list)
    sources: list[RetrievedChunk] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)

    def cite(self, chunk: RetrievedChunk) -> None:
        if chunk.chunk_id not in {c.chunk_id for c in self.sources}:
            self.sources.append(chunk)


def requested_checks(message: str) -> set[str]:
    # A customer may explicitly set a past issue aside and ask a new question.
    current = re.sub(
        r"\bleave\b[^.!?]{0,70}?\bfor later\b|(?:房态|库存|预订).{0,6}(?:先不查|稍后再说)",
        "",
        message,
        flags=re.I,
    )
    checks: set[str] = set()
    if _has(r"促销|活动价|特价|promotion|promotional|special offer", current):
        checks.add("promotion")
    if _has(r"尾款|余款|remaining payment|final payment|\bbalance\b", current) and _has(
        r"期限|哪天|何时|抵达|出发|天|when|deadline|due|days?|arrival|departure", current
    ):
        checks.add("balance")
    if _has(r"退[订定]金|退款|取消|refund|cancell?ation|\bcancel\b", current):
        checks.add("refund")
    if _has(
        r"房态|库存|有房|有空房|能订到|availability|hotel.{0,55}\bavailable\b|room.{0,55}\bavailable\b",
        current,
    ):
        checks.add("inventory")
    if _has(
        r"(?:已|是否|确认|订妥).{0,6}(?:预订|订上|订好)|(?:预订|订单).{0,10}(?:成功|完成|确认)|"
        r"\bbooked\b|(?:booking|reservation).{0,40}(?:complete|confirm)|(?:confirm|proof).{0,45}(?:booking|reservation)",
        current,
    ):
        checks.add("booking")
    return checks


_SEARCH = {
    "promotion": "promotion validity dates historical price special offer effective end date",
    "balance": "quotation payment balance due before arrival before departure short answers",
    "refund": "deposit refund cancellation policy refundable non-refundable booking terms",
}


def handoff_query(checks: set[str]) -> str:
    return " | ".join(_SEARCH[key] for key in _SEARCH if key in checks)


def _clauses(chunk: RetrievedChunk, zh: bool) -> list[str]:
    clauses: list[str] = []
    for raw in chunk.text.splitlines():
        line = raw.strip().removeprefix("- ").strip()
        if not line or line.startswith(("#", "Q:")) or line.endswith(("?", "？")):
            continue
        # Bilingual handbook paragraphs repeat the same rule.
        halves = re.split(r"(?<=[。！？])\s+(?=[A-Za-z])", line, maxsplit=1)
        localized = halves[0 if zh else -1]
        clauses.extend(
            part.strip()
            for part in re.split(r"(?<=[。.!?])\s+|(?<=[。！？])", localized)
            if part.strip()
        )
    return clauses


def _offer_window(text: str) -> tuple[date, date] | None:
    if _has(
        r"without effective dates|no (?:effective|validity) dates|没有生效日期|未注明有效期", text
    ):
        return None
    iso = re.search(
        r"(20\d\d-\d\d-\d\d)\s*(?:to|through|until|至|到|[–—])\s*(20\d\d-\d\d-\d\d)", text, re.I
    )
    try:
        if iso:
            start, end = (date.fromisoformat(s) for s in iso.groups())
            return (start, end) if start <= end else None
        if not _has(r"仅适用|限定|限时|only|valid (?:for|during)", text):
            return None
        cn = re.search(r"(20\d{2})年(\d{1,2})月", text)
        if cn:
            year, month = map(int, cn.groups())
        else:
            month_year = re.search(r"\b([A-Za-z]+ 20\d\d)\s+only\b", text, re.I)
            if not month_year:
                return None
            parsed = datetime.strptime(month_year[1], "%B %Y")
            year, month = parsed.year, parsed.month
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    except (ValueError, OverflowError):
        return None


def _check_offer(
    review: SalesReview, message: str, chunks: list[RetrievedChunk], zh: bool, today: date
) -> None:
    candidates = [
        c
        for c in chunks
        if _has(
            r"促销价|活动价|特价|promotional? (?:rate|price)|promotion was|promotion of|special offer",
            c.text,
        )
    ]
    amounts = re.findall(r"(?:CNY|RMB|¥|￥)\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*元", message, re.I)
    if amounts:
        values = [left or right for left, right in amounts]
        candidates = [
            c
            for c in candidates
            if any(re.search(r"(?<!\d)" + re.escape(value) + r"(?!\d)", c.text) for value in values)
        ]
    window = None
    if candidates and len({c.text for c in candidates}) == 1:
        review.cite(candidates[0])
        window = _offer_window(candidates[0].text)
    if window:
        start, end = window
        if today > end:
            status = (
                f"该促销已截止，最后有效日期为 {end}。" if zh else f"The promotion ended on {end}."
            )
        elif today < start:
            status = (
                f"该促销的有效期尚未开始（{start} 至 {end}）。"
                if zh
                else f"The offer starts on {start} and ends on {end}."
            )
        else:
            status = (
                f"手册列出的促销日期为 {start} 至 {end}，当前在此范围内。"
                if zh
                else f"Today falls within the stated promotion period ({start} to {end})."
            )
    else:
        status = (
            "资料缺少可核实的有效期，无法判断该活动是否仍有效或已过期。"
            if zh
            else "There is no verifiable validity period to establish the promotion's status."
        )
    review.notes.append(
        status
        + (
            " 当前价格需销售核实后报价。"
            if zh
            else " Sales must verify the current price before quoting."
        )
    )


def _policy_conflict(
    review: SalesReview, check: str, chunks: list[RetrievedChunk], message: str, zh: bool
) -> None:
    alternatives: dict[tuple, dict[str, tuple[RetrievedChunk, str]]] = {}
    for chunk in chunks:
        for sentence in _clauses(chunk, zh):
            scope: tuple
            if check == "balance":
                if not _has(r"balance|尾款|余款", sentence):
                    continue
                side = (
                    "arrival"
                    if _has(r"arrival|抵达|抵达前|到达", sentence)
                    else "departure"
                    if _has(r"departure|出发", sentence)
                    else ""
                )
                scope = (chunk.region, chunk.product_name, "balance")
            else:
                if not _has(r"refund|退[款费]|不退|全退", sentence):
                    continue
                side = (
                    "nonrefundable"
                    if _has(r"non[- ]?refundable|no refund|不退", sentence)
                    else "refundable"
                    if _has(r"full refund|全额退|全退", sentence)
                    else ""
                )
                relative = re.search(
                    r"(?:出发前|抵达前)\s*(\d+)\s*天|\b(\d+)\s*days? before (?:departure|arrival)",
                    sentence,
                    re.I,
                )
                if not relative:
                    continue
                days = relative[1] or relative[2]
                asked = re.search(
                    r"(?:出发前|抵达前)\s*(\d+)\s*天|\b(\d+)\s*days? before", message, re.I
                )
                if asked and (asked[1] or asked[2]) != days:
                    continue
                anchor = "arrival" if _has(r"抵达前|before arrival", relative[0]) else "departure"
                scope = (chunk.region, chunk.product_name, anchor, days)
            if side:
                alternatives.setdefault(scope, {}).setdefault(side, (chunk, sentence))
    conflict = next((pair for pair in alternatives.values() if len(pair) == 2), None)
    if not conflict:
        return
    conflict_source_ids = {chunk.chunk_id for chunk, _ in conflict.values()}
    if len(conflict_source_ids.union(c.chunk_id for c in review.sources)) <= 3:
        for chunk, quote in conflict.values():
            review.cite(chunk)
            review.notes.append(
                f"《{chunk.source_title}》：{quote}" if zh else f"{chunk.source_title}: {quote}"
            )
        review.notes.append(
            "以上条款存在冲突，需由销售核对订单适用条款后确认。"
            if zh
            else "The terms conflict. Sales must verify which provision applies to this booking."
        )
    else:
        review.notes.append(
            "其他付款或退款条件需销售核对订单条款。"
            if zh
            else "Sales must check the additional payment or refund terms against the order."
        )


def assess_sales_review(
    checks: set[str],
    message: str,
    chunks: list[RetrievedChunk],
    facts: list[ConversationFact],
    destination: str | None,
    language: str,
    today: date,
) -> SalesReview:
    review = SalesReview()
    zh = language == "zh"
    region = REGIONS.get(destination or "")
    scoped = [c for c in chunks if not destination or c.region in {"general", region}]
    if "promotion" in checks:
        _check_offer(review, message, scoped, zh, today)
    for policy in ("balance", "refund"):
        if policy in checks:
            _policy_conflict(review, policy, scoped, message, zh)
    if "inventory" in checks:
        if _has(
            r"(?:儿童|小孩).{0,10}(?:房价|价格|核价)|child(?:ren)?(?: hotel| room)? (?:price|rate|cost)",
            message,
        ):
            review.notes.append(
                "具体儿童房价需由销售向酒店核价后确认。"
                if zh
                else "Sales must verify the exact child room price with the hotel."
            )
        review.notes.append(
            "指定日期房态需由销售向供应商核实库存，目前无法确认有房。"
            if zh
            else "Sales must check supplier inventory for date-specific availability. Availability is unconfirmed."
        )
        dated = any(f.key == "travel_date" and f.status not in UNRESOLVED for f in facts)
        if not dated and not _has(r"\d+\s+[A-Za-z]+\s+20\d\d|20\d\d[年/-]\d{1,2}", message):
            review.questions.append(
                "请提供需要核查的入住日期。" if zh else "Which check-in date should sales verify?"
            )
    if "booking" in checks:
        review.notes.append(
            "目前没有订单凭据可以确认预订完成，需由销售核对订单记录与供应商确认单。"
            if zh
            else "Booking completion is unconfirmed. Sales must verify the order record and supplier confirmation."
        )
    return review


def publish_review(
    review: SalesReview,
    draft: ReplyDraft,
    topics: tuple[Topic, ...],
    chunks: list[RetrievedChunk],
    facts: list[ConversationFact],
    language: str,
    message: str,
) -> ReplyDraft:
    points = find_points(topics, chunks)
    notes, questions = point_guidance(topics, points, facts, language, message)
    questions = list(dict.fromkeys([*questions, *review.questions]))
    lines = [*(display_quote(p, language) for p in points), *notes, *review.notes, *questions]
    body = "\n".join(lines)
    cited = {c.chunk_id: c for c in [*review.sources, *point_chunks(points)] if c in chunks}
    return draft.model_copy(
        update={
            "body_text": body,
            "display_text": body,
            "open_questions": questions,
            "source_ids": list(cited),
            "generation_method": "rag_grounded_template" if cited else "context_template",
            "evidence": [
                {
                    "chunk_id": c.chunk_id,
                    "source_title": c.source_title,
                    "section": c.section,
                    "text": c.text,
                    "sha256": hashlib.sha256(c.text.encode()).hexdigest(),
                }
                for c in cited.values()
            ],
            "internal_note": "销售需核实待确认事项。"
            if language == "zh"
            else "Sales verification required.",
            "recommended_products": [],
        }
    )
