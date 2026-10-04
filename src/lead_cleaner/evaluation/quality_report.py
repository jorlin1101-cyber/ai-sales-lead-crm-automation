"""Sealed quality evidence, append-only decisions, and explicit quality gates.

Trust context is supplied by a verified Git/CI adapter. Report fields never grant
trust, and every check reloads the original files before interpreting evidence.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from ._quality_reviews import EMPTY_REVIEW_SET, effective_assertions, verify_provenance
from ._quality_storage import (
    QualityReportError,
    assertion_key,
    key_set,
    load_run,
    object_hash,
    seal_run,
    write_record,
)
from .quality_checks import compare_retrieval_reports

__all__ = [
    "EMPTY_REVIEW_SET",
    "QualityReportError",
    "accept_baseline",
    "evaluate_gate",
    "load_run",
    "seal_run",
    "write_decision",
    "write_record",
]
_FINGERPRINTS = (
    "mode",
    "protocol_id",
    "protocol_hash",
    "evaluator_hash",
    "suite_hash",
    "knowledge_hash",
    "environment_hash",
)
_ISSUE_FIELDS = (
    "mode",
    "case_id",
    "probe_id",
    "checkpoint",
    "assertion_id",
    "failure_type",
    "severity",
)


def _issue_matches(issue: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    return (
        issue.get("status") == "open"
        and all(issue.get(field) == row.get(field) for field in _ISSUE_FIELDS)
        and bool(issue.get("issue_id"))
        and bool(issue.get("failure_type"))
    )


def _validate_issues(issues: list[dict[str, Any]]) -> None:
    ids: set[str] = set()
    for issue in issues:
        identifier = issue.get("issue_id")
        if (
            not isinstance(identifier, str)
            or not identifier
            or identifier in ids
            or issue.get("status") not in {"open", "resolved"}
        ):
            raise QualityReportError("Known-issue identity or lifecycle is invalid.")
        ids.add(identifier)
        if any(
            not isinstance(issue.get(field), str) or not issue[field] for field in _ISSUE_FIELDS
        ):
            raise QualityReportError("Known issues require exact assertion and failure signatures.")
        if issue["status"] == "resolved" and not issue.get("resolved_commit"):
            raise QualityReportError("Resolved issues must identify the fixing commit.")


def _fresh(run: Mapping[str, Any], expected: Iterable[Iterable[str]]) -> dict[str, Any]:
    fresh = load_run(run["directory"], expected_keys=expected)
    if fresh["manifest_hash"] != run.get("manifest_hash"):
        raise QualityReportError("Run reference differs from the sealed manifest.")
    return fresh


def _comparable(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> None:
    if any(
        not candidate["metadata"].get(field)
        or baseline["metadata"].get(field) != candidate["metadata"].get(field)
        for field in _FINGERPRINTS
    ):
        raise QualityReportError("Baseline and candidate fingerprints are incomparable.")
    if key_set(baseline["metadata"]["expected_keys"]) != key_set(
        candidate["metadata"]["expected_keys"]
    ):
        raise QualityReportError("Baseline and candidate assertion coverage differs.")


def _baseline_run(record: Mapping[str, Any], trust: Mapping[str, Any]) -> dict[str, Any]:
    run = record["run"]
    trusted_digest = trust.get("accepted_baselines", {}).get(record.get("acceptance_id"))
    if trusted_digest is None or trusted_digest != run["manifest_hash"]:
        raise QualityReportError("Baseline acceptance is not bound to a trusted manifest.")
    return _fresh(run, run["metadata"]["expected_keys"])


def _row_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old = {assertion_key(row): row for row in before}
    return [
        {
            "key": list(assertion_key(row)),
            "before": old[assertion_key(row)]["behavior_status"],
            "after": row["behavior_status"],
            "execution_status": row["execution_status"],
        }
        for row in after
        if old[assertion_key(row)]["behavior_status"] != row["behavior_status"]
        or old[assertion_key(row)]["execution_status"] != row["execution_status"]
    ]


def evaluate_gate(
    gate_kind: str,
    runs: list[dict[str, Any]],
    *,
    candidate_sha: str,
    expected_keys_by_mode: Mapping[str, Iterable[Iterable[str]]],
    baselines: Mapping[str, dict[str, Any]] | None = None,
    known_issues: list[dict[str, Any]] | None = None,
    review_set: dict[str, Any] | None = None,
    trust_context: dict[str, Any] | None = None,
    required_modes: Iterable[str] | None = None,
    provenance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate a fixed evidence set; callers persist the returned decision separately."""
    trust, issues, baseline_records = trust_context or {}, known_issues or [], baselines or {}
    fixed_review = review_set if review_set is not None else EMPTY_REVIEW_SET
    decision: dict[str, Any] = {
        "decision_id": uuid4().hex,
        "gate_kind": gate_kind,
        "candidate_sha": candidate_sha,
        "exit_code": 0,
        "suite_release_status": "not_evaluated",
        "product_release_status": "not_evaluated",
        "reasons": [],
        "runs": [],
        "comparison": {},
        "review_set_hash": object_hash(fixed_review),
        "known_issues_hash": object_hash(issues),
        "provisional": False,
    }

    def reason(
        code: int, message: str, *, mode: str | None = None, key: tuple[str, ...] | None = None
    ) -> None:
        item: dict[str, Any] = {"exit_code": code, "message": message}
        if mode is not None:
            item["mode"] = mode
        if key is not None:
            item["key"] = list(key)
        decision["reasons"].append(item)
        decision["exit_code"] = max(decision["exit_code"], code)

    if gate_kind not in {"inventory", "regression", "release"}:
        reason(2, "Unknown gate kind.")
        return decision
    if not candidate_sha:
        reason(3, "Expected candidate SHA must be supplied independently of the reports.")
    try:
        _validate_issues(issues)
    except QualityReportError as exc:
        reason(3, str(exc))
    if (
        gate_kind == "regression"
        and issues
        and trust.get("known_issues_hash") != object_hash(issues)
    ):
        reason(3, "Known-issue exemptions are not from a verified accepted source.")
    modes = (
        set(required_modes)
        if required_modes is not None
        else (
            {"rule_only", "mocked_model", "live"}
            if gate_kind == "release"
            else {run.get("metadata", {}).get("mode", "") for run in runs}
        )
    )
    seen: set[str] = set()
    release_fingerprint: tuple[Any, ...] | None = None
    if not runs:
        reason(2, "No sealed runs supplied.")
    for supplied in runs:
        mode = supplied.get("metadata", {}).get("mode", "")
        if mode in seen:
            reason(3, "Duplicate mode report.", mode=mode)
            continue
        seen.add(mode)
        try:
            if mode not in expected_keys_by_mode:
                raise QualityReportError("Mode has no externally supplied expected-key set.")
            run = _fresh(supplied, expected_keys_by_mode[mode])
            metadata = run["metadata"]
            if metadata.get("tested_commit") != candidate_sha:
                raise QualityReportError("Report tested SHA differs from the expected candidate.")
            if any(not metadata.get(field) for field in _FINGERPRINTS):
                raise QualityReportError("Run is missing a reproducibility fingerprint.")
            if gate_kind == "release":
                fingerprint = tuple(metadata[field] for field in _FINGERPRINTS if field != "mode")
                if release_fingerprint is not None and fingerprint != release_fingerprint:
                    reason(
                        3,
                        "Release modes use different protocols, evaluators, samples, knowledge, or environments.",
                        mode=mode,
                    )
                release_fingerprint = fingerprint
            rows, review_hash, review_ids = effective_assertions(run, fixed_review, trust)
            is_provisional = (
                metadata.get("provisional") is not False
                or metadata.get("source_dirty") is True
                or metadata.get("business_labels_reviewed") is not True
            )
            decision["provisional"] = decision["provisional"] or is_provisional
            run_ref = {
                "mode": mode,
                "manifest_hash": run["manifest_hash"],
                "review_set_hash": review_hash,
                "review_ids": review_ids,
            }
            decision["runs"].append(run_ref)
            if gate_kind == "release" and is_provisional:
                reason(
                    3,
                    "Provisional, dirty, or unreviewed evidence cannot authorize release.",
                    mode=mode,
                )
            if gate_kind == "release" or trust.get("require_provenance", False):
                try:
                    run_ref["provenance"] = verify_provenance(run, provenance or [], trust)
                except QualityReportError as exc:
                    reason(3, str(exc), mode=mode)
            incomplete = [row for row in rows if row["execution_status"] != "completed"]
            for row in incomplete:
                reason(
                    2,
                    "An applicable assertion was not successfully executed.",
                    mode=mode,
                    key=assertion_key(row),
                )
            if gate_kind == "inventory":
                if mode == "rule_only":
                    _check_subreports(
                        run,
                        run,
                        {},
                        lambda code, message, **details: (
                            reason(code, message, **details) if code != 1 else None
                        ),
                    )
                continue
            for row in rows:
                if (
                    row["execution_status"] == "completed"
                    and row["behavior_status"] == "needs_review"
                ):
                    reason(
                        1,
                        "An applicable assertion still needs human judgment.",
                        mode=mode,
                        key=assertion_key(row),
                    )
                if (
                    gate_kind == "release"
                    and row.get("mandatory", True)
                    and row["execution_status"] == "completed"
                    and row["behavior_status"] == "fail"
                ):
                    reason(
                        1,
                        "A mandatory behavior assertion failed.",
                        mode=mode,
                        key=assertion_key(row),
                    )
            baseline_record = baseline_records.get(mode)
            if gate_kind == "regression" or mode == "rule_only":
                if baseline_record is None:
                    raise QualityReportError("A trusted accepted baseline is required.")
                latest = trust.get("latest_accepted_baselines")
                if (
                    not isinstance(latest, dict)
                    or latest.get(mode) != baseline_record["acceptance_id"]
                ):
                    raise QualityReportError(
                        "The supplied baseline is not the latest accepted version."
                    )
                baseline = _baseline_run(baseline_record, trust)
                _comparable(baseline, run)
                old_rows, _, _ = effective_assertions(
                    baseline, baseline_record.get("review_set"), trust
                )
                if any(
                    row["execution_status"] != "completed"
                    or row["behavior_status"] == "needs_review"
                    for row in old_rows
                ):
                    raise QualityReportError(
                        "Accepted baseline is incomplete or still needs review."
                    )
                comparison = {
                    "accepted_baseline": baseline_record["acceptance_id"],
                    "changes": _row_changes(old_rows, rows),
                }
                decision["comparison"][mode] = comparison
                initial_record = baseline_record.get("initial_baseline")
                if initial_record is not None:
                    initial = _baseline_run(initial_record, trust)
                    _comparable(initial, run)
                    initial_rows, _, _ = effective_assertions(
                        initial, initial_record.get("review_set"), trust
                    )
                    comparison["initial_baseline"] = initial_record["acceptance_id"]
                    comparison["initial_changes"] = _row_changes(initial_rows, rows)
                if gate_kind == "regression":
                    before = {assertion_key(row): row for row in old_rows}
                    for row in rows:
                        key = assertion_key(row)
                        previous = before[key]
                        if (
                            row["execution_status"] != "completed"
                            or row["behavior_status"] == "needs_review"
                        ):
                            continue
                        if row["behavior_status"] == "fail" and (
                            previous["behavior_status"] != "fail"
                            or previous.get("failure_type") != row.get("failure_type")
                            or previous.get("severity") != row.get("severity")
                            or not any(_issue_matches(issue, row) for issue in issues)
                        ):
                            reason(
                                1,
                                "New failure, changed failure signature, or resolved defect recurrence.",
                                mode=mode,
                                key=key,
                            )
                if mode == "rule_only":
                    _check_subreports(run, baseline, comparison, reason)
        except (QualityReportError, KeyError, TypeError, ValueError) as exc:
            reason(3, str(exc), mode=mode)
    for mode in sorted(modes - seen):
        reason(2, "Required mode report is missing.", mode=mode)
    if gate_kind == "release":
        decision["suite_release_status"] = "passed" if decision["exit_code"] == 0 else "blocked"
    return decision


def _check_subreports(
    run: dict[str, Any], baseline: dict[str, Any], comparison: dict[str, Any], reason: Any
) -> None:
    required = {"retrieval-v4", "recommendation-contract"}
    if not required <= set(run["subreports"]):
        reason(2, "A required rule-only subreport is missing.", mode="rule_only")
        return
    contract = run["subreports"]["recommendation-contract"]
    if (
        contract.get("schema_version") != "recommendation-contract-report-v1"
        or contract.get("kind") != "data_contract"
        or contract.get("case_count") != 12
        or not isinstance(contract.get("checks"), list)
        or not contract["checks"]
    ):
        raise QualityReportError(
            "Recommendation subreport does not satisfy the frozen data contract."
        )
    if contract.get("status") != "pass" or any(
        check.get("pass") is not True for check in contract["checks"]
    ):
        reason(1, "Recommendation data-contract validation failed.", mode="rule_only")
    if "retrieval-v4" not in baseline["subreports"]:
        raise QualityReportError("Accepted baseline has no retrieval reference.")
    result = compare_retrieval_reports(
        baseline["subreports"]["retrieval-v4"], run["subreports"]["retrieval-v4"]
    )
    comparison["retrieval"] = result
    if not result["comparable"]:
        reason(
            3,
            "Retrieval reports are incomparable: " + "; ".join(result["errors"]),
            mode="rule_only",
        )
    elif result["status"] == "fail":
        reason(1, "A per-query retrieval metric regressed.", mode="rule_only")


def write_decision(output_dir: str | Path, decision: Mapping[str, Any]) -> Path:
    """Append a decision in a new directory; never update sealed run summaries."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    write_record(directory / "decision.json", decision)
    write_record(directory / "comparison.json", decision.get("comparison", {}))
    lines = [
        "# 质量门槛判断",
        "",
        f"门槛：{decision['gate_kind']}",
        f"受测候选：{decision['candidate_sha']}",
        f"返回码：{decision['exit_code']}",
        f"候选证据（provisional）：{decision.get('provisional', False)}",
        f"本套件发布状态：{decision['suite_release_status']}",
        "整体产品发布：未评估（not_evaluated）。本判断不能替代整个 P0 验收。",
        "",
        "原因：",
        "",
    ]
    lines.extend(
        f"- [{item['exit_code']}] {item['message']}" for item in decision.get("reasons", [])
    )
    if not decision.get("reasons"):
        lines.append("- 当前门槛条件满足。inventory 成功不表示业务质量通过。")
    lines.extend(["", "版本比较：", ""])
    for mode, comparison in decision.get("comparison", {}).items():
        lines.append(
            f"- {mode}：最近认可基线 {comparison.get('accepted_baseline')}；变化 {len(comparison.get('changes', []))} 项。"
        )
        if "initial_baseline" in comparison:
            lines.append(
                f"- {mode}：首次基线 {comparison['initial_baseline']}；累计变化 {len(comparison.get('initial_changes', []))} 项。"
            )
    with (directory / "summary.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return directory


def accept_baseline(
    run: dict[str, Any],
    *,
    previous: dict[str, Any] | None,
    known_issues: list[dict[str, Any]],
    approval: dict[str, Any],
    trust_context: dict[str, Any],
    review_set: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a proposed immutable acceptance unit after independently verified approval.

    Persist this record and its issue snapshot together in the reviewed Git change.
    This function cannot move a branch or advance a baseline index itself.
    """
    fresh = _fresh(run, run["metadata"]["expected_keys"])
    metadata = fresh["metadata"]
    if (
        metadata.get("provisional") is not False
        or metadata.get("source_dirty") is not False
        or metadata.get("business_labels_reviewed") is not True
    ):
        raise QualityReportError(
            "Only clean, reviewed, nonprovisional runs can become accepted baselines."
        )
    _validate_issues(known_issues)
    latest = trust_context.get("latest_accepted_baselines")
    if not isinstance(latest, dict):
        raise QualityReportError("Acceptance requires an explicit verified latest-baseline index.")
    current = latest.get(metadata["mode"])
    if current != (previous["acceptance_id"] if previous else None):
        raise QualityReportError(
            "Accepted predecessor changed; rerun comparison against the latest version."
        )
    inventory = evaluate_gate(
        "inventory",
        [fresh],
        candidate_sha=metadata["tested_commit"],
        expected_keys_by_mode={metadata["mode"]: metadata["expected_keys"]},
        review_set=review_set,
        trust_context=trust_context,
    )
    if inventory["exit_code"] != 0:
        raise QualityReportError("Baseline initialization requires a complete valid inventory.")
    rows, review_hash, _ = effective_assertions(fresh, review_set, trust_context)
    binding = {
        "tested_commit": metadata["tested_commit"],
        "manifest_hash": fresh["manifest_hash"],
        "review_set_hash": review_hash,
        "previous_acceptance_id": previous["acceptance_id"] if previous else None,
        "known_issues_hash": object_hash(known_issues),
    }
    approved = trust_context.get("approval_bindings", {}).get(approval.get("approval_ref"))
    if approved != binding:
        raise QualityReportError("Acceptance has no externally verified approval binding.")
    if any(
        row["execution_status"] != "completed" or row["behavior_status"] == "needs_review"
        for row in rows
    ):
        raise QualityReportError("Baseline initialization requires complete, adjudicated evidence.")
    if any(
        row["behavior_status"] == "fail"
        and not any(_issue_matches(issue, row) for issue in known_issues)
        for row in rows
    ):
        raise QualityReportError(
            "Every baseline failure must match an explicitly registered open defect."
        )
    if previous is not None:
        result = evaluate_gate(
            "regression",
            [fresh],
            candidate_sha=metadata["tested_commit"],
            expected_keys_by_mode={metadata["mode"]: metadata["expected_keys"]},
            baselines={metadata["mode"]: previous},
            known_issues=known_issues,
            review_set=review_set,
            trust_context=trust_context,
        )
        if result["exit_code"] != 0:
            raise QualityReportError(
                "Baseline advancement requires a passing regression against the accepted predecessor."
            )
    issues = copy.deepcopy(known_issues)
    for issue in issues:
        matching = [
            row
            for row in rows
            if all(issue.get(field) == row.get(field) for field in _ISSUE_FIELDS[:5])
        ]
        if (
            issue["status"] == "open"
            and matching
            and all(row["behavior_status"] == "pass" for row in matching)
        ):
            issue.update(status="resolved", resolved_commit=metadata["tested_commit"])
    acceptance_id = approval.get("acceptance_id") or uuid4().hex
    if acceptance_id in trust_context.get("accepted_baselines", {}):
        raise QualityReportError("An accepted record ID cannot be reused or overwritten.")
    initial = (
        previous.get("initial_acceptance_id", previous["acceptance_id"])
        if previous
        else acceptance_id
    )
    initial_record = (previous.get("initial_baseline") or previous) if previous else None
    return {
        "initial_baseline": initial_record,
        "acceptance_id": acceptance_id,
        "initial_acceptance_id": initial,
        "previous_acceptance_id": binding["previous_acceptance_id"],
        "run": fresh,
        "review_set": review_set or EMPTY_REVIEW_SET,
        "review_set_hash": review_hash,
        "known_issues": issues,
        "known_issues_hash": object_hash(issues),
        "approval_ref": approval["approval_ref"],
        "tested_commit": metadata["tested_commit"],
        "manifest_hash": fresh["manifest_hash"],
    }
