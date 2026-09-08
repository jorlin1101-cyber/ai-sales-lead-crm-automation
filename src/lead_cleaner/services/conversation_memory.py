"""Pure, testable fact and opportunity updates. No model or external side effects."""

import re

from lead_cleaner.schemas.conversation import ConversationFact
from lead_cleaner.schemas.policy import LeadFeatures
from lead_cleaner.services.service_preferences import FLEXIBLE, normalize_preference

OPT_OUT = re.compile(
    r"退订|不要再联系|别再联系|停止联系|取消咨询|unsubscribe|do not contact|stop contacting|^\s*not interested[.!\s]*$",
    re.I,
)
CORRECTION = re.compile(
    r"改成|改为|改去|更正|纠正|实际上|现在改|不是.+是|不再需要|不要|不用|无需|actually|instead|correction|change",
    re.I,
)


def merge_facts(
    previous: list[ConversationFact], incoming: list[ConversationFact], message: str
) -> list[ConversationFact]:
    merged = {fact.key: fact for fact in previous}
    for fact in incoming:
        old = merged.get(fact.key)
        equivalent_preference = old and normalize_preference(
            fact.key, old.value
        ) == normalize_preference(fact.key, fact.value)
        flexible_update = old and (fact.value == FLEXIBLE or old.value == FLEXIBLE)
        from lead_cleaner.services.conversation_slots import equivalent_budget

        pending_update = fact.status == "pending" or (old and old.status == "pending")
        same_budget = old and fact.key == "budget" and equivalent_budget(old.value, fact.value)
        if (
            old
            and old.value != fact.value
            and not equivalent_preference
            and not flexible_update
            and not pending_update
            and not same_budget
            and not CORRECTION.search(message)
        ):
            equivalent = fact.key == "travel_date" and (
                old.value in fact.value or fact.value in old.value
            )
            if not equivalent:
                fact = fact.model_copy(
                    update={
                        "value": f"{old.value} / {fact.value}"[:500],
                        "status": "conflicted",
                        "confidence": min(old.confidence, fact.confidence),
                    }
                )
        merged[fact.key] = fact
    return list(merged.values())


def cumulative_features(
    previous: LeadFeatures | None, current: LeadFeatures, facts: list[ConversationFact]
) -> LeadFeatures:
    values = current.model_dump()
    if previous is not None:
        for name in (
            "asks_for_price",
            "asks_for_availability",
            "requests_private_or_custom_service",
            "requests_partnership",
            "company_name_present",
        ):
            values[name] = values[name] or getattr(previous, name)
        values["cleaned_message_length"] = min(
            5000, previous.cleaned_message_length + current.cleaned_message_length
        )
        if current.customer_kind in {"unknown", "individual"}:
            values["customer_kind"] = previous.customer_kind
    known = {fact.key: fact.value for fact in facts if fact.status not in {"conflicted", "pending"}}
    values["group_size"] = (
        int(known["group_size"]) if known.get("group_size", "").isdigit() else None
    )
    values["destinations"] = [known["destination"]] if "destination" in known else []
    values["mentions_specific_dates"] = "travel_date" in known
    values["conflict_codes"] = [
        f"conflicting_{fact.key}" for fact in facts if fact.status == "conflicted"
    ][:10]
    return LeadFeatures.model_validate(values)
