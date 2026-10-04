"""Versioned, strict contracts at evaluation input and artifact boundaries."""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Mode = Literal["rule_only", "mocked_model", "live"]
Severity = Literal["critical", "major", "minor"]
ExecutionStatus = Literal["completed", "error", "not_run", "not_applicable"]
BehaviorStatus = Literal["pass", "fail", "needs_review"]
MODES: tuple[Mode, ...] = ("rule_only", "mocked_model", "live")
SCHEMA_VERSION = "p0-quality.v1"
KEY_FIELDS = ("mode", "case_id", "probe_id", "checkpoint", "assertion_id", "trial_id")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssertionSpec(StrictRecord):
    assertion_id: str = Field(min_length=1)
    probe_id: str = "main"
    checkpoint: str = "result"
    observation_scope: Literal["function", "api", "persistence", "reply"] = "function"
    check: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    mandatory: bool = True
    severity: Severity = "major"
    manual_review: bool = False
    applicable_modes: list[Mode] = Field(default_factory=lambda: list(MODES))


class CaseSpec(StrictRecord):
    case_id: str = Field(min_length=1)
    case_version: int = Field(default=1, ge=1)
    family: str
    language: str
    source: Literal["synthetic", "redacted_real"] = "synthetic"
    applicable_modes: list[Mode] = Field(min_length=1)
    adapter: str = Field(min_length=1)
    adapter_version: str = "v1"
    suite_role: Literal["regression"] = "regression"
    exposure_status: Literal["visible"] = "visible"
    grading_profile: str = "p0-01-ai-assisted.v1"
    rubric_version: str = "p0-rubric.v1"
    payload: dict[str, Any]
    assertions: list[AssertionSpec] = Field(min_length=1)
    review_status: Literal["draft", "reviewed"] = "draft"
    reviewer: str | None = None
    reviewed_at: str | None = None
    review_reason: str | None = None
    related_cases: list[str] = Field(default_factory=list)
    relation_type: str | None = None

    @model_validator(mode="after")
    def unique_assertions(self) -> "CaseSpec":
        if self.review_status == "reviewed" and not all(
            (self.reviewer, self.reviewed_at, self.review_reason)
        ):
            raise ValueError("reviewed cases require reviewer, time and rationale")
        keys = [(a.probe_id, a.checkpoint, a.assertion_id) for a in self.assertions]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate assertion identity")
        if len(set(self.applicable_modes)) != len(self.applicable_modes):
            raise ValueError("duplicate applicable mode")
        return self


class AssertionResult(StrictRecord):
    mode: Mode
    case_id: str
    probe_id: str
    checkpoint: str
    assertion_id: str
    trial_id: str
    execution_status: ExecutionStatus
    behavior_status: BehaviorStatus | None
    mandatory: bool = True
    severity: Severity = "major"
    manual_review: bool = False
    failure_type: str | None = None
    known_issue_id: str | None = None
    actual: Any = None
    expected: Any = None
    observation_hash: str | None = None

    @model_validator(mode="after")
    def execution_and_behavior(self) -> "AssertionResult":
        if self.execution_status != "completed" and self.behavior_status is not None:
            raise ValueError("unexecuted assertion cannot carry a business verdict")
        if self.execution_status == "completed" and self.behavior_status is None:
            raise ValueError("completed assertion requires a business verdict")
        if self.behavior_status == "needs_review" and not self.manual_review:
            raise ValueError("needs_review requires an explicitly manual assertion")
        return self


def result_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row[name]) for name in KEY_FIELDS)


def expected_keys(cases: list[dict[str, Any]], mode: str, trials: int = 1) -> list[list[str]]:
    if mode not in MODES or trials < 1:
        raise ValueError("invalid mode or trial count")
    keys = []
    for raw in cases:
        case = CaseSpec.model_validate(raw)
        if mode not in case.applicable_modes:
            continue
        for trial in range(1, trials + 1):
            for spec in case.assertions:
                if mode in spec.applicable_modes:
                    keys.append(
                        [
                            mode,
                            case.case_id,
                            spec.probe_id,
                            spec.checkpoint,
                            spec.assertion_id,
                            str(trial),
                        ]
                    )
    if len({tuple(key) for key in keys}) != len(keys):
        raise ValueError("duplicate expected key")
    return keys
