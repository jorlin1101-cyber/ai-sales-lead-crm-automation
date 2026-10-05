"""Independent inventory, regression, behavior, and baseline-acceptance gates."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from .provenance import require_verified_artifact
from .reports import (
    FINGERPRINTS,
    KEY_FIELDS,
    METRICS,
    ReportError,
    content_hash,
    key,
    load_run,
    write_record,
)
from .trust import EMPTY_REVIEW_SET, effective_assertions

ISSUE_FIELDS = tuple(f for f in KEY_FIELDS if f != "trial_id") + ("failure_type", "severity")


def _issues(issues: list[dict[str, Any]]) -> None:
    seen = set()
    for issue in issues:
        if (
            not issue.get("issue_id")
            or issue["issue_id"] in seen
            or issue.get("status") not in {"open", "resolved"}
            or any(not isinstance(issue.get(f), str) or not issue[f] for f in ISSUE_FIELDS)
        ):
            raise ReportError("Known issues require unique identity and exact failure signature")
        if (
            issue["protocol_id"] != "p0-02.v1"
            or issue["severity"] not in {"critical", "major", "minor"}
            or issue["status"] == "resolved"
            and not issue.get("resolved_commit")
        ):
            raise ReportError("Invalid known-issue protocol or lifecycle")
        seen.add(issue["issue_id"])


def _matches(issue: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    return issue["status"] == "open" and all(issue.get(f) == row.get(f) for f in ISSUE_FIELDS)


def _fresh(
    run: Mapping[str, Any],
    expected: Iterable[Any] | None = None,
    retrieval: Iterable[Any] | None = None,
) -> dict[str, Any]:
    result = load_run(run["directory"], expected_keys=expected, expected_retrieval_keys=retrieval)
    if result["manifest_hash"] != run.get("manifest_hash"):
        raise ReportError("Run reference differs from sealed evidence")
    return result


def _comparable(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    if any(before["metadata"].get(f) != after["metadata"].get(f) for f in FINGERPRINTS) or any(
        before["metadata"].get(f) != after["metadata"].get(f)
        for f in ("expected_keys", "expected_retrieval_keys", "rubric_hash")
    ):
        raise ReportError("Baseline and candidate have different frozen comparison inputs")


def _baseline(record: Mapping[str, Any], trust: Mapping[str, Any]) -> dict[str, Any]:
    run = _fresh(record["run"])
    if trust.get("accepted_baselines", {}).get(record.get("acceptance_id")) != run["manifest_hash"]:
        raise ReportError("Baseline manifest is not independently accepted")
    return run


def compare_retrieval(
    baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if [(r["case_id"], r["path"]) for r in baseline] != [
        (r["case_id"], r["path"]) for r in candidate
    ]:
        raise ReportError("Retrieval comparison covers different query paths")
    regressions = []
    for before, after in zip(baseline, candidate, strict=True):
        if before.get("query") != after.get("query"):
            raise ReportError("Retrieval input query changed")
        for name in METRICS:
            old, new = before["metrics"][name], after["metrics"][name]
            if (
                old["applicability"] != new["applicability"]
                or name != "unjudged_rate"
                and old.get("denominator") != new.get("denominator")
            ):
                raise ReportError("Retrieval metric applicability or planned denominator changed")
            if new["applicability"] == "incomplete_judgments":
                raise ReportError("Unknown retrieval metrics cannot be compared")
            if new["applicability"] == "applicable" and (
                new["value"] > old["value"]
                if name == "unjudged_rate"
                else new["value"] < old["value"]
            ):
                regressions.append(
                    {
                        "case_id": after["case_id"],
                        "path": after["path"],
                        "metric": name,
                        "baseline": old["value"],
                        "candidate": new["value"],
                    }
                )
    return regressions


def evaluate_gate(
    gate_kind: str,
    runs: list[dict[str, Any]],
    *,
    candidate_sha: str,
    expected_keys_by_mode: Mapping[str, Iterable[Any]],
    expected_retrieval_keys_by_mode: Mapping[str, Iterable[Any]],
    baselines: Mapping[str, dict[str, Any]] | None = None,
    known_issues: list[dict[str, Any]] | None = None,
    review_set: dict[str, Any] | None = None,
    trust_context: dict[str, Any] | None = None,
    required_modes: Iterable[str] | None = None,
    dataset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trust, issues, baseline_records = trust_context or {}, known_issues or [], baselines or {}
    decision: dict[str, Any] = {
        "decision_id": uuid4().hex,
        "gate_kind": gate_kind,
        "candidate_sha": candidate_sha,
        "exit_code": 0,
        "suite_behavior_status": "not_evaluated",
        "suite_release_status": "not_evaluated",
        "product_release_status": "not_evaluated",
        "provisional": False,
        "reasons": [],
        "runs": [],
        "comparison": {},
        "effective_assertions": {},
        "derived_adjudications": {},
        "known_issues_hash": content_hash(issues),
        "review_set_hash": content_hash(review_set or EMPTY_REVIEW_SET),
    }

    def reason(code: int, message: str, mode: str | None = None) -> None:
        decision["exit_code"] = max(code, decision["exit_code"])
        decision["reasons"].append({"exit_code": code, "message": message, "mode": mode})

    if gate_kind not in {"inventory", "regression", "behavior"}:
        reason(2, "Unknown gate")
        return decision
    if not candidate_sha:
        reason(3, "An independently supplied candidate SHA is required")
    try:
        _issues(issues)
        if gate_kind == "regression" and trust.get("known_issues_hash") != content_hash(issues):
            raise ReportError("Known-issue exemptions are not independently trusted")
    except ReportError as exc:
        reason(3, str(exc))
    required = (
        set(required_modes)
        if required_modes is not None
        else (
            {"rule_only", "mocked_model"}
            if gate_kind == "behavior"
            else {r["metadata"]["mode"] for r in runs}
        )
    )
    if not runs:
        reason(2, "No reports supplied")
    seen = set()
    common_fingerprint = None
    for supplied in runs:
        mode = supplied.get("metadata", {}).get("mode", "")
        if mode in seen:
            reason(3, "Duplicate mode report", mode)
            continue
        seen.add(mode)
        try:
            if mode not in expected_keys_by_mode or mode not in expected_retrieval_keys_by_mode:
                raise ReportError("No independently supplied expected-key set")
            run = _fresh(
                supplied, expected_keys_by_mode[mode], expected_retrieval_keys_by_mode[mode]
            )
            metadata = run["metadata"]
            fingerprint = tuple(metadata[f] for f in FINGERPRINTS if f != "mode")
            if common_fingerprint is not None and fingerprint != common_fingerprint:
                raise ReportError("Mode reports have different comparison fingerprints")
            common_fingerprint = fingerprint
            if metadata.get("tested_commit") != candidate_sha:
                raise ReportError("Report tested a different candidate SHA")
            provisional = (
                metadata.get("provisional") is not False
                or metadata.get("source_dirty") is not False
                or metadata.get("business_labels_reviewed") is not True
            )
            decision["provisional"] |= provisional
            if gate_kind != "inventory" and provisional:
                reason(
                    3, "Unreviewed labels or dirty/provisional evidence cannot formally pass", mode
                )
            rows, review_hash, review_ids = effective_assertions(
                run, review_set, trust, dataset=dataset
            )
            record: dict[str, Any] = {}
            baseline: dict[str, Any] = {}
            previous: list[dict[str, Any]] = []
            decision["derived_adjudications"][mode] = []
            if gate_kind == "regression":
                selected = baseline_records.get(mode)
                if selected is None:
                    raise ReportError(
                        "Regression must use the latest independently accepted baseline"
                    )
                record = selected
                if trust.get("latest_accepted_baselines", {}).get(mode) != record.get(
                    "acceptance_id"
                ):
                    raise ReportError(
                        "Regression must use the latest independently accepted baseline"
                    )
                baseline = _baseline(record, trust)
                _comparable(baseline, run)
                previous, _, _ = effective_assertions(
                    baseline, record.get("review_set"), trust, dataset=dataset
                )
                if any(
                    r["execution_status"] != "completed" or r["behavior_status"] == "needs_review"
                    for r in previous
                ):
                    raise ReportError("Accepted baseline is incomplete or unreviewed")
                if dataset is not None and any(
                    r["behavior_status"] == "needs_review" for r in rows
                ):
                    from .review_reuse import reuse_reviewed_assertions

                    original_rows = copy.deepcopy(rows)
                    rows, derived = reuse_reviewed_assertions(
                        baseline, record, run, rows, trust, dataset
                    )
                    if [key(r) for r in rows] != [key(r) for r in original_rows]:
                        raise ReportError("Review reuse changed the planned assertion set")
                    frozen = KEY_FIELDS + (
                        "execution_status",
                        "observation_hash",
                        "severity",
                        "mandatory",
                        "manual_review",
                    )
                    for original, effective in zip(original_rows, rows, strict=True):
                        if any(original.get(field) != effective.get(field) for field in frozen):
                            raise ReportError("Review reuse changed frozen assertion provenance")
                        if (
                            original["behavior_status"] != "needs_review"
                            or original.get("review_ids")
                        ) and original != effective:
                            raise ReportError(
                                "Review reuse cannot override automatic or current human results"
                            )
                    decision["derived_adjudications"][mode] = derived
            decision["effective_assertions"][mode] = rows
            decision["runs"].append(
                {
                    "mode": mode,
                    "manifest_hash": run["manifest_hash"],
                    "review_set_hash": review_hash,
                    "review_ids": review_ids,
                }
            )
            for row in rows:
                if row["execution_status"] != "completed":
                    reason(
                        2,
                        "An applicable assertion was not executed successfully: "
                        + "/".join(key(row)),
                        mode,
                    )
                elif gate_kind != "inventory" and row["behavior_status"] == "needs_review":
                    reason(
                        1,
                        "A required assertion still needs semantic review: " + "/".join(key(row)),
                        mode,
                    )
                elif (
                    gate_kind == "behavior"
                    and row.get("mandatory", True)
                    and row["behavior_status"] == "fail"
                ):
                    reason(1, "A mandatory behavior assertion failed: " + "/".join(key(row)), mode)
            for result in run["retrieval"]:
                if result["execution_status"] != "completed":
                    reason(2, "Retrieval path was not successfully executed", mode)
                for metric in result["metrics"].values():
                    if metric.get("error_count", 0) or metric.get("not_run_count", 0):
                        reason(2, "Retrieval metric execution is incomplete", mode)
                    elif gate_kind != "inventory" and (
                        metric["applicability"] == "incomplete_judgments"
                        or metric.get("needs_review_count", 0)
                    ):
                        reason(1, "Retrieval metric still needs judgment", mode)
            if gate_kind != "regression":
                continue
            before = {key(row): row for row in previous}
            changes = []
            for row in rows:
                old = before[key(row)]
                if old["behavior_status"] != row["behavior_status"]:
                    changes.append(
                        {
                            "key": list(key(row)),
                            "before": old["behavior_status"],
                            "after": row["behavior_status"],
                        }
                    )
                if row["behavior_status"] == "fail" and (
                    old["behavior_status"] != "fail"
                    or not any(_matches(issue, row) and _matches(issue, old) for issue in issues)
                ):
                    reason(1, "New, recurrent, or unapproved failure: " + "/".join(key(row)), mode)
            comparison = {"accepted_baseline": record["acceptance_id"], "changes": changes}
            decision["comparison"][mode] = comparison
            initial_record = record.get("initial_baseline") or record
            initial = _baseline(initial_record, trust)
            _comparable(initial, run)
            initial_rows, _, _ = effective_assertions(
                initial, initial_record.get("review_set"), trust, dataset=dataset
            )
            initial_map = {key(row): row for row in initial_rows}
            comparison["initial_baseline"] = initial_record["acceptance_id"]
            comparison["initial_changes"] = [
                {
                    "key": list(key(r)),
                    "before": initial_map[key(r)]["behavior_status"],
                    "after": r["behavior_status"],
                }
                for r in rows
                if initial_map[key(r)]["behavior_status"] != r["behavior_status"]
            ]
            if all(
                r["execution_status"] == "completed"
                and all(m["applicability"] != "incomplete_judgments" for m in r["metrics"].values())
                for r in run["retrieval"]
            ):
                regressions = compare_retrieval(baseline["retrieval"], run["retrieval"])
                comparison["retrieval_regressions"] = regressions
                if regressions:
                    reason(1, "A per-query retrieval metric regressed", mode)
        except (ReportError, KeyError, TypeError, ValueError) as exc:
            reason(3, str(exc), mode)
    for mode in sorted(required - seen):
        reason(2, "Required mode report is missing", mode)
    if gate_kind == "behavior":
        decision["suite_behavior_status"] = "passed" if decision["exit_code"] == 0 else "blocked"
    return decision


def write_decision(output: str | Path, decision: Mapping[str, Any]) -> Path:
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=False)
    write_record(directory / "decision.json", decision)
    write_record(directory / "comparison.json", decision["comparison"])
    summary = f"P0-02 检查：{decision['gate_kind']}\n候选版本：{decision['candidate_sha']}\n返回码：{decision['exit_code']}\n临时报告：{decision['provisional']}\n本套件业务检查：{decision['suite_behavior_status']}；整体产品发布未评估；真实模型未测。\n"
    inherited = sum(len(items) for items in decision.get("derived_adjudications", {}).values())
    summary += f"相同语义输入沿用旧审核：{inherited} 项；派生记录不是本轮新增人工审核。\n"
    summary += "\n".join(str(r["message"]) for r in decision["reasons"])
    from .reports import write_bytes

    write_bytes(directory / "summary.md", summary.encode("utf-8"))
    return directory


def accept_baseline(
    run: dict[str, Any],
    *,
    previous: dict[str, Any] | None,
    known_issues: list[dict[str, Any]],
    approval: dict[str, Any],
    trust_context: dict[str, Any],
    review_set: dict[str, Any] | None = None,
    dataset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fresh = _fresh(run)
    meta = fresh["metadata"]
    if (
        meta.get("provisional") is not False
        or meta.get("source_dirty") is not False
        or meta.get("business_labels_reviewed") is not True
    ):
        raise ReportError("Baseline acceptance requires clean, reviewed, nonprovisional evidence")
    _issues(known_issues)
    if not isinstance(trust_context.get("latest_accepted_baselines"), dict) or trust_context[
        "latest_accepted_baselines"
    ].get(meta["mode"]) != (previous["acceptance_id"] if previous else None):
        raise ReportError("Accepted predecessor changed or latest index is missing")
    if trust_context.get("known_issues_hash") != content_hash(known_issues):
        raise ReportError("Baseline issue snapshot is not independently approved")
    artifact = require_verified_artifact(fresh, trust_context)
    result = evaluate_gate(
        "inventory",
        [fresh],
        candidate_sha=meta["tested_commit"],
        expected_keys_by_mode={meta["mode"]: meta["expected_keys"]},
        expected_retrieval_keys_by_mode={meta["mode"]: meta["expected_retrieval_keys"]},
        review_set=review_set,
        trust_context=trust_context,
        dataset=dataset,
    )
    if result["exit_code"]:
        raise ReportError("Baseline requires a complete valid inventory")
    rows, review_hash, _ = effective_assertions(fresh, review_set, trust_context, dataset=dataset)
    if any(
        r["execution_status"] != "completed" or r["behavior_status"] == "needs_review" for r in rows
    ) or any(
        m["applicability"] == "incomplete_judgments" or m.get("needs_review_count", 0)
        for r in fresh["retrieval"]
        for m in r["metrics"].values()
    ):
        raise ReportError("Unknown or unreviewed evidence cannot become a baseline")
    if any(
        r["behavior_status"] == "fail" and not any(_matches(i, r) for i in known_issues)
        for r in rows
    ):
        raise ReportError("Every baseline failure needs an exact approved open issue")
    binding = {
        "protocol_id": meta["protocol_id"],
        "tested_commit": meta["tested_commit"],
        "manifest_hash": fresh["manifest_hash"],
        "protocol_hash": meta["protocol_hash"],
        "dataset_hash": meta["dataset_hash"],
        "rubric_hash": meta.get("rubric_hash", meta["evaluator_hash"]),
        "review_set_hash": review_hash,
        "known_issues_hash": content_hash(known_issues),
        "previous_acceptance_id": previous["acceptance_id"] if previous else None,
    }
    if trust_context.get("approval_bindings", {}).get(approval.get("approval_ref")) != binding:
        raise ReportError("No independently approved exact baseline binding")
    if previous is not None:
        regression = evaluate_gate(
            "regression",
            [fresh],
            candidate_sha=meta["tested_commit"],
            expected_keys_by_mode={meta["mode"]: meta["expected_keys"]},
            expected_retrieval_keys_by_mode={meta["mode"]: meta["expected_retrieval_keys"]},
            baselines={meta["mode"]: previous},
            known_issues=known_issues,
            review_set=review_set,
            trust_context=trust_context,
            dataset=dataset,
        )
        if regression["exit_code"]:
            raise ReportError("Baseline advancement requires a passing latest regression")
    acceptance_id = approval.get("acceptance_id")
    if not acceptance_id or acceptance_id in trust_context.get("accepted_baselines", {}):
        raise ReportError("Acceptance ID must be new and explicit")
    issues = copy.deepcopy(known_issues)
    for issue in issues:
        matching = [r for r in rows if all(issue.get(f) == r.get(f) for f in ISSUE_FIELDS[:-2])]
        if (
            issue["status"] == "open"
            and matching
            and all(r["behavior_status"] == "pass" for r in matching)
        ):
            issue.update(status="resolved", resolved_commit=meta["tested_commit"])
    return {
        "acceptance_id": acceptance_id,
        "approval_ref": approval["approval_ref"],
        "approval_binding": binding,
        "initial_acceptance_id": previous.get("initial_acceptance_id", previous["acceptance_id"])
        if previous
        else acceptance_id,
        "previous_acceptance_id": binding["previous_acceptance_id"],
        "initial_baseline": (previous.get("initial_baseline") or previous) if previous else None,
        "run": fresh,
        "review_set": review_set or EMPTY_REVIEW_SET,
        "review_set_hash": review_hash,
        "manifest_hash": fresh["manifest_hash"],
        "known_issues": issues,
        "known_issues_hash": content_hash(issues),
        "provenance": artifact,
    }


def accept_baselines(
    runs: list[dict[str, Any]],
    *,
    previous: dict[str, Any],
    known_issues: list[dict[str, Any]],
    approvals: dict[str, Any],
    trust_context: dict[str, Any],
    review_set: dict[str, Any] | None = None,
    dataset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Propose BOTH mode updates as one Git-reviewed unit; never mutate live pointers."""
    if (
        len(runs) != 2
        or {r["metadata"]["mode"] for r in runs} != {"rule_only", "mocked_model"}
        or len({r["metadata"]["tested_commit"] for r in runs}) != 1
    ):
        raise ReportError("Atomic acceptance requires both modes of one candidate")
    if len({tuple(r["metadata"][f] for f in FINGERPRINTS if f != "mode") for r in runs}) != 1:
        raise ReportError("Atomic acceptance modes must share comparison fingerprints")
    units = {
        run["metadata"]["mode"]: accept_baseline(
            run,
            previous=previous.get(run["metadata"]["mode"]),
            known_issues=known_issues,
            approval=approvals[run["metadata"]["mode"]],
            trust_context=trust_context,
            review_set=review_set,
            dataset=dataset,
        )
        for run in runs
    }
    issues = copy.deepcopy(known_issues)
    for issue in issues:
        unit = units.get(issue["mode"])
        if unit:
            issue.update(
                next(i for i in unit["known_issues"] if i["issue_id"] == issue["issue_id"])
            )
    for unit in units.values():
        unit["known_issues"] = copy.deepcopy(issues)
        unit["known_issues_hash"] = content_hash(issues)
    return {
        "protocol_id": "p0-02.v1",
        "expected_previous_latest": dict(trust_context["latest_accepted_baselines"]),
        "accepted": units,
        "initial": {mode: unit["initial_baseline"] or unit for mode, unit in units.items()},
        "latest_accepted_baselines": {mode: unit["acceptance_id"] for mode, unit in units.items()},
        "accepted_baselines": dict(trust_context.get("accepted_baselines", {}))
        | {unit["acceptance_id"]: unit["manifest_hash"] for unit in units.values()},
        "known_issues": issues,
        "known_issues_hash": content_hash(issues),
    }
