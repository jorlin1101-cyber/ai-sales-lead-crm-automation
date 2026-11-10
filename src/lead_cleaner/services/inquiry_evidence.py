"""Evidence selection for specific customer questions within a multi-turn inquiry.

Question phrases route retrieval; prices, conditions and services come exclusively
from supplied source text. Never promote general transport to an airport transfer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.conversation import ConversationFact
from lead_cleaner.services.conversation_slots import REGIONS, UNRESOLVED
from lead_cleaner.services.knowledge_localization import source_bullets


@dataclass(frozen=True)
class Topic:
    key: str
    question: str
    source: str
    query: str
    label_zh: str
    label_en: str


GENERAL_TOPICS = frozenset({"deposit", "payment_methods", "pricing_basis", "quote_exclusions"})


TOPICS = (
    Topic(
        "pricing_basis",
        r"定价|计价|核价原则|报价因素|pricing (?:principles|basis|variables)|how.{0,32}pric(?:ed|ing)|what.{0,24}(?:determines|affects).{0,15}(?:price|cost)",
        r"pricing is calculated based|按.{0,50}(?:组合核价|定价)|报价.{0,30}取决于",
        "pricing variables group size hotel level vehicle guide season",
        "定价依据",
        "Pricing basis",
    ),
    Topic(
        "child_policy",
        r"(?:儿童|小孩|孩子|小朋友).{0,16}(?:优惠|折扣|价|费用)|(?:child(?:ren)?|kids?)[\s-]{0,2}(?:discount|(?:room |hotel )?price|rate|fare|pay|eligible)|discount.{0,16}(?:child|kid)",
        r"(?:child|children|kids?).{0,70}(?:discount|reduced rate)|(?:儿童|孩子|小孩).{0,22}(?:优惠|核价|折扣)",
        "family child discounts age sharing room with parents reduced rate",
        "儿童优惠",
        "Child discount",
    ),
    Topic(
        "deposit",
        r"(?:定金|订金|首付).{0,12}(?:比例|百分|几成|多少)|(?:多少|几成).{0,10}(?:定金|订金)|\bdeposit\b.{0,26}(?:percentage|percent|required|confirm|how much)|(?:percentage|how much|percent).{0,23}\bdeposit\b",
        r"(?:\d+(?:\.\d+)?\s*%.{0,20}(?:deposit|定金|订金)|(?:deposit|定金|订金).{0,20}\d+(?:\.\d+)?\s*%)",
        "private tour quotation notes booking deposit confirm",
        "订金",
        "Booking deposit",
    ),
    Topic(
        "payment_methods",
        r"支付方式|付款方式|怎么付|如何付款|怎样付|接受.{0,8}(?:支付|付款)|支持.{0,6}(?:支付|付款)|(?:付款|支付).{0,10}(?:渠道|方法|途径)|能用.{0,12}支付|(?:methods?|ways?|forms?) of pay|payment (?:methods?|options?)|how (?:can|do|should|may) (?:we|i) pay|(?:which|what).{0,22}payments?.{0,16}accept",
        r"pay(?:ment)? methods|bank (?:wire|transfer)|paypal|银行(?:转账|电汇)|支付宝",
        "credit card bank transfer",
        "付款方式",
        "Payment methods",
    ),
    Topic(
        "airport_transfer",
        r"接送|接机|送机|机场.{0,15}(?:往返|接驳)|airport.{0,22}(?:transfers?|pickup|pick.up|drop.off|shuttle)|transfers?.{0,24}(?:included|airport)",
        r"(?:机场|airport).{0,65}(?:接送|接机|送机|transfer|pickup|pick.up|drop.off)|(?:transfer|pickup|pick.up|drop.off).{0,50}airport",
        "airport transfers arrival departure airport city hotel",
        "机场接送",
        "Airport transfers",
    ),
    Topic(
        "activity_dates",
        r"免费.{0,10}(?:手工|手作|活动|体验)|(?:手工|手作|workshop|craft).{0,35}(?:日期|参加|eligible|eligibility|qualify|included|date range)|(?:eligible|qualify|included|complimentary|free).{0,32}(?:workshop|craft)|活动.{0,12}(?:日期|适用范围|时间范围)",
        r"(?:出发|depart|departure).{0,100}(?:免费.{0,8}(?:手工|手作|体验|活动)|workshop)|(?:complimentary|free).{0,50}(?:workshop|craft).{0,95}(?:depart|valid|from)",
        "complimentary workshop eligibility departure dates date range",
        "活动适用期",
        "Workshop eligibility",
    ),
    Topic(
        "classic_route",
        r"(?:云南|经典|亲子).{0,13}(?:路线|线路|行程)|路线.{0,8}城市|经典行程|classic.{0,30}itinerary|standard itinerary|cities and duration",
        r"classic.{0,40}itinerary|经典.{0,12}线路|(?:昆明|Kunming).{0,12}(?:大理|Dali).{0,18}(?:丽江|Lijiang)",
        "classic itinerary duration and cities typical duration",
        "经典线路",
        "Classic itinerary",
    ),
    Topic(
        "quote_exclusions",
        r"(?:不含|不包括|排除|另付).{0,12}(?:费用|机票|保险)|(?:机票|保险).{0,22}(?:包含|包括)|(?:哪些|什么).{0,9}(?:不含|排除)|exclud(?:ed|es|sions?)|(?:flight|insurance).{0,30}(?:included|cover)",
        r"excluded items|不含项|不含.{0,34}(?:保险|航班|机票)",
        "quotation notes",
        "报价不含项",
        "Quotation exclusions",
    ),
)


def inquiry_topics(message: str) -> tuple[Topic, ...]:
    topics = tuple(t for t in TOPICS if re.search(t.question, message, re.I))
    # General pricing/product recommendations keep their existing richer product flow.
    if topics and all(t.key in {"pricing_basis", "classic_route"} for t in topics):
        return ()
    return topics


def _source_lines(chunk: RetrievedChunk) -> list[str]:
    lines = [
        s.strip().removeprefix("- ").strip()
        for s in chunk.text.splitlines()
        if s.strip() and not s.lstrip().startswith("#")
    ]
    # In a FAQ the question is not a statement of policy.
    return [s.split("A: ", 1)[-1] for s in lines if not s.startswith("Q:") or "A: " in s]


@dataclass(frozen=True)
class SupportedPoint:
    topic: Topic
    chunk: RetrievedChunk
    quote: str


def find_points(
    topics: tuple[Topic, ...], chunks: list[RetrievedChunk], destination: str | None = None
) -> list[SupportedPoint]:
    region = REGIONS.get(destination or "")
    eligible = [c for c in chunks if not destination or c.region in {"general", region}]
    found = []
    for topic in topics:
        # Product-specific conditions need a matching product's evidence; deposits and payment
        # methods prefer general terms when these are available.
        ranked = sorted(
            eligible,
            key=lambda c: (
                bool(region) and c.region != ("general" if topic.key in GENERAL_TOPICS else region),
                c.rank,
                -c.score,
                c.chunk_id,
            ),
        )
        for chunk in ranked:
            quotes = [line for line in _source_lines(chunk) if re.search(topic.source, line, re.I)]
            if quotes:
                found.append(SupportedPoint(topic, chunk, _only_requested_clause(topic, quotes[0])))
                break
    return found


def transfer_background(
    topics: tuple[Topic, ...], chunks: list[RetrievedChunk], destination: str | None = None
) -> list[SupportedPoint]:
    """General transportation evidence can explain what remains unverified."""
    topic = next((t for t in topics if t.key == "airport_transfer"), None)
    if topic is None:
        return []
    region = REGIONS.get(destination or "")
    for chunk in chunks:
        if destination and chunk.region not in {region, "general"}:
            continue
        for line in _source_lines(chunk):
            if re.search(r"private (?:vehicle|transport)|vehicle type|私人用车|专车", line, re.I):
                return [SupportedPoint(topic, chunk, line)]
    return []


def point_chunks(points: list[SupportedPoint], limit: int = 3) -> list[RetrievedChunk]:
    return list({p.chunk.chunk_id: p.chunk for p in points}.values())[:limit]


def _only_requested_clause(topic: Topic, text: str) -> str:
    if topic.key == "quote_exclusions":
        exclusions = re.search(r"excluded items\s*\(([^)]*)\)", text, re.I)
        if exclusions:
            return exclusions.group()
    if topic.key == "deposit":
        for clause in re.split(r"(?<=[.!?。！？])\s+|(?<=[。！？])|[；;，]", text):
            if re.search(topic.source, clause, re.I):
                return clause.strip()
    return text


def display_quote(point: SupportedPoint, language: str) -> str:
    quote = point.quote
    if point.topic.key == "quote_exclusions":
        match = re.fullmatch(r"excluded items\s*\(([^)]+)\)", quote, re.I)
        if match:
            if language == "en":
                return "The quotation excludes " + match[1].strip() + "."
            terms = {
                "flights": "机票",
                "visa fees": "签证费",
                "tips": "小费",
                "personal expenses": "个人消费",
                "travel insurance": "旅行保险",
            }
            items = [word.strip() for word in match[1].split(",")]
            return "报价不包含" + "、".join(terms.get(item.lower(), item) for item in items) + "。"
    if language == "zh":
        under = re.search(
            r"children under (\d+) at reduced rate when sharing room with parents", quote, re.I
        )
        if point.topic.key == "child_policy" and under:
            return f"未满{under[1]}岁的儿童与父母同住一间房时可享儿童优惠。"
        if point.topic.key == "payment_methods" and "most currencies" in quote.lower():
            for line in source_bullets(point.chunk, language):
                if (
                    re.search(point.topic.source, line, re.I)
                    and not line.startswith("原文（译文待复核）")
                    and "Stripe" in line
                ):
                    return line + "手册注明 Stripe 信用卡服务适用于大多数币种。"
        for line in source_bullets(point.chunk, language):
            if re.search(point.topic.source, line, re.I) and not line.startswith(
                "原文（译文待复核）"
            ):
                quote = _only_requested_clause(point.topic, line)
                break
    sections = re.split(r"(?<=[。！？])\s+(?=[A-Z])", quote, maxsplit=1)
    if len(sections) == 2:
        return sections[0] if language == "zh" else sections[1]
    return quote


def _departure(facts: list[ConversationFact]) -> date | None:
    for f in facts:
        if f.key != "travel_date" or f.status in UNRESOLVED:
            continue
        m = re.fullmatch(r"(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})(?:日|号)?", f.value)
        if m:
            try:
                return date(*(int(n) for n in m.groups()))
            except ValueError:
                pass
        for form in ("%d %B %Y", "%B %d, %Y", "%B %d %Y"):
            try:
                return datetime.strptime(f.value, form).date()
            except ValueError:
                continue
    return None


def _activity_window(text: str) -> tuple[date, date] | None:
    match = re.search(
        r"(20\d{2})年(\d{1,2})月(\d{1,2})日\s*(?:至|到|[-–])\s*(?:(20\d{2})年)?(?:(\d{1,2})月)?(\d{1,2})日",
        text,
    )
    if match:
        y, m, d, y2, m2, d2 = match.groups()
        try:
            return date(int(y), int(m), int(d)), date(int(y2 or y), int(m2 or m), int(d2))
        except ValueError:
            return None
    english = re.search(
        r"\bfrom (\d{1,2}) (?:to|through|until) (\d{1,2}) ([A-Za-z]+ 20\d{2})", text, re.I
    )
    if english:
        first, last, month_year = english.groups()
        try:
            return datetime.strptime(f"{first} {month_year}", "%d %B %Y").date(), datetime.strptime(
                f"{last} {month_year}", "%d %B %Y"
            ).date()
        except ValueError:
            pass
    return None


def _child_eligibility(message: str, quote: str, zh: bool) -> tuple[str, str]:
    # Both personal facts and a verifiable eligibility rule are required for a decision.
    limit = re.search(
        r"(?:under|younger than)\s+(\d{1,2})|(?:未满|不满)(\d{1,2})岁|(\d{1,2})岁以下", quote, re.I
    )
    if (
        not limit
        or not re.search(r"(?:sharing.{0,35}parents|与父母同住)", quote, re.I)
        or not re.search(r"reduced rate|可享.{0,6}优惠", quote, re.I)
    ):
        return "", ""
    age = re.search(
        r"(?:孩子|儿童|小孩|小朋友|child|kid).{0,12}?(\d{1,2})\s*(?:岁|years? old|years? of age)|(?:our |my )?(\d{1,2})-year-old",
        message,
        re.I,
    )
    room = re.search(
        r"(?:与|和|跟)父母同住|(?:与|和|跟)父母住.{0,6}(?:同一间|一间)|(?:shares?|sharing).{0,25}(?:us|parents)",
        message,
        re.I,
    )
    uncertain_room = re.search(
        r"(?:没|未|不确定|是否|不|not sure|not decided|whether).{0,10}(?:与父母同住|同住|sharing|share)",
        message,
        re.I,
    )
    own_eligibility = re.search(r"能享受|符合|qualify|eligible|entitled", message, re.I)
    if not own_eligibility:
        return "", ""
    if age and room and not uncertain_room:
        threshold = int(next(x for x in limit.groups() if x))
        years = int(next(x for x in age.groups() if x))
        meets = years < threshold
        return (
            (
                "按您提供的年龄与同住安排，"
                + ("符合" if meets else "不符合")
                + "手册所列的儿童优惠条件。"
            )
            if zh
            else (
                "Based on the age and room arrangement you supplied, your child "
                + ("meets" if meets else "does not meet")
                + " the handbook’s discount conditions."
            )
        ), ""
    ask = []
    if not age:
        ask.append("孩子的年龄" if zh else "your child’s age")
    if not room or uncertain_room:
        ask.append(
            "是否与父母同住一间房" if zh else "whether your child shares a room with a parent"
        )
    return "", (
        "请确认" + "和".join(ask) + "。" if zh else "Could you confirm " + " and ".join(ask) + "?"
    ) if ask else ""


def point_guidance(
    topics: tuple[Topic, ...],
    points: list[SupportedPoint],
    facts: list[ConversationFact],
    language: str,
    message: str,
) -> tuple[list[str], list[str]]:
    zh = language == "zh"
    by_key = {p.topic.key: p for p in points}
    notes = []
    if re.search(
        r"(?:刚才|更正|先前|上述).{0,12}人数|(?:revised|corrected|updated) (?:group|party) size",
        message,
        re.I,
    ):
        group = next(
            (f.value for f in facts if f.key == "group_size" and f.status not in UNRESOLVED), None
        )
        if group:
            notes.append(
                f"本次按已确认的 {group} 人回复。"
                if zh
                else f"The confirmed group size is {group}."
            )
    questions = []
    for topic in topics:
        point = by_key.get(topic.key)
        if point is None:
            notes.append(
                (
                    f"关于{topic.label_zh}，现有资料未能核实，需销售核对。"
                    if zh
                    else f"Sales needs to verify {topic.label_en.lower()}; the available information does not establish it."
                )
            )
            continue
        if topic.key == "child_policy":
            detail, needed = _child_eligibility(message, point.quote, zh)
            if detail:
                notes.append(detail)
            if needed:
                questions.append(needed)
        if topic.key == "child_policy" and re.search(
            r"具体|价格|多少钱|房价|exact|room price|how much|cost", message, re.I
        ):
            notes.append(
                "手册未列具体儿童价格或折扣比例，需由销售结合入住安排核价。"
                if zh
                else "Sales must verify the exact child price for the room and travel arrangements."
            )
        if topic.key == "activity_dates":
            depart = _departure(facts)
            window = _activity_window(point.quote)
            if depart and window:
                eligible = window[0] <= depart <= window[1]
                if zh:
                    notes.append(
                        f"您提供的出发日期 {depart.isoformat()} {'符合' if eligible else '不符合'}上述活动日期条件。"
                    )
                else:
                    notes.append(
                        f"Your departure date {depart.isoformat()} {'meets' if eligible else 'is outside'} the stated eligibility window."
                    )
            elif depart is None and not re.search(r"日期适用范围|date range", message, re.I):
                questions.append(
                    "您的出发日期是什么时候？" if zh else "What is your departure date?"
                )
    return notes, questions
