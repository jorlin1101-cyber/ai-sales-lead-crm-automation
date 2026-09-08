"""Deterministic estimate from operator-maintained prices, never from model-generated numbers."""

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QuoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product: str = Field(min_length=1, max_length=100)
    travel_date: date
    group_size: int = Field(ge=1, le=10000)
    hotel_tier: str = Field(min_length=1, max_length=100)
    currency: Literal["CNY", "USD", "EUR"]


class PriceRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    product: str
    hotel_tier: str
    currency: Literal["CNY", "USD", "EUR"]
    valid_from: date
    valid_until: date
    min_people: int = Field(default=1, ge=1)
    max_people: int = Field(default=10000, ge=1)
    per_person: Decimal = Field(ge=0, allow_inf_nan=False)
    fixed_group_cost: Decimal = Field(default=Decimal("0"), ge=0, allow_inf_nan=False)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1, allow_inf_nan=False)
    included: list[str] = Field(min_length=1)
    excluded: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(min_length=1)
    demo_only: bool = False

    @model_validator(mode="after")
    def ranges(self):
        if self.valid_until < self.valid_from or self.max_people < self.min_people:
            raise ValueError("Invalid pricing rule ranges")
        return self


def estimate_quote(
    request: QuoteInput,
    rules_path: Path | None,
    *,
    today: date | None = None,
    allow_demo: bool = False,
) -> dict:
    today = today or date.today()
    if request.travel_date < today:
        raise ValueError("Travel date is in the past.")
    if rules_path is None or not rules_path.is_file():
        raise ValueError("No verified price rules configured; a salesperson must supply prices.")
    rules = [
        PriceRule.model_validate(item)
        for item in json.loads(rules_path.read_text(encoding="utf-8"))
    ]
    matching = [
        rule
        for rule in rules
        if rule.product == request.product
        and rule.hotel_tier == request.hotel_tier
        and rule.currency == request.currency
        and rule.valid_from <= request.travel_date <= rule.valid_until
        and rule.min_people <= request.group_size <= rule.max_people
        and (allow_demo or not rule.demo_only)
    ]
    if len(matching) != 1:
        raise ValueError("Missing or overlapping price rules; manual pricing is required.")
    rule = matching[0]
    subtotal = rule.per_person * request.group_size + rule.fixed_group_cost
    tax = (subtotal * rule.tax_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def money(amount: Decimal) -> str:
        return str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    return {
        "status": "estimate_requires_review",
        "currency": rule.currency,
        "inputs": request.model_dump(mode="json"),
        "rule_id": rule.rule_id,
        "rule_version": rule.version,
        "rule_sha256": hashlib.sha256(rule.model_dump_json().encode()).hexdigest(),
        "per_person": money(rule.per_person),
        "fixed_group_cost": money(rule.fixed_group_cost),
        "subtotal": money(subtotal),
        "tax": money(tax),
        "total": money(subtotal + tax),
        "included": rule.included,
        "excluded": rule.excluded,
        "assumptions": rule.assumptions,
        "valid_until": min(
            today + timedelta(days=7), request.travel_date, rule.valid_until
        ).isoformat(),
        "demo_only": rule.demo_only,
    }
