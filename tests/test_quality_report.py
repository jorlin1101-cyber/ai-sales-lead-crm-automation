"""Integrity, provenance, review, and regression invariants for quality evidence."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from lead_cleaner.evaluation._quality_reviews import effective_assertions, verify_provenance
from lead_cleaner.evaluation._quality_storage import (
    _checked_file,
    _read_lines,
    assertion_key,
    file_hash,
    json_bytes,
    key_set,
    object_hash,
    read_json,
)
from lead_cleaner.evaluation.quality_report import (
    EMPTY_REVIEW_SET,
    QualityReportError,
    accept_baseline,
    evaluate_gate,
    load_run,
    seal_run,
    write_decision,
    write_record,
)
from lead_cleaner.rag.evaluation_report import run_keyword_evaluation


@pytest.fixture(scope="module")
def retrieval():
    return run_keyword_evaluation(
        chunks_path="data/knowledge_snapshot/knowledge_chunks.json",
        eval_queries_path="data/rag_eval/eval_queries.json",
    )


@pytest.fixture
def factory(tmp_path, retrieval):
    counter = 0

    def make(
        *,
        mode="mocked_model",
        behavior="pass",
        execution="completed",
        metadata=None,
        row=None,
        subreports=None,
    ):
        nonlocal counter
        counter += 1
        observation = {
            "mode": mode,
            "case_id": "case",
            "probe_id": "main",
            "checkpoint": "result",
            "trial_id": "1",
            "execution_status": execution,
            "data": {"answer": "Evidence-backed answer."},
        }
        assertion = {
            "mode": mode,
            "case_id": "case",
            "probe_id": "main",
            "checkpoint": "result",
            "assertion_id": "safe",
            "trial_id": "1",
            "execution_status": execution,
            "behavior_status": behavior if execution == "completed" else None,
            "mandatory": True,
            "severity": "critical",
            "manual_review": behavior == "needs_review",
            "failure_type": "unsupported_fact" if behavior == "fail" else None,
            "known_issue_id": None,
            "actual": observation["data"],
            "expected": "supported fact",
            "observation_hash": object_hash(observation),
        }
        assertion.update(row or {})
        meta = {
            "mode": mode,
            "run_id": f"run-{counter}",
            "tested_commit": "candidate",
            "provisional": False,
            "source_dirty": False,
            "business_labels_reviewed": True,
            "protocol_id": "p0.v1",
            "protocol_hash": "protocol",
            "evaluator_hash": "evaluator",
            "rubric_hash": "rubric",
            "suite_hash": "suite",
            "knowledge_hash": "knowledge",
            "environment_hash": "env",
            "expected_keys": [list(assertion_key(assertion))],
        }
        meta.update(metadata or {})
        reports = (
            {}
            if mode != "rule_only"
            else {
                "retrieval-v4": deepcopy(retrieval),
                "recommendation-contract": {
                    "schema_version": "recommendation-contract-report-v1",
                    "kind": "data_contract",
                    "case_count": 12,
                    "status": "pass",
                    "checks": [{"pass": True}],
                },
            }
        )
        if subreports is not None:
            reports = subreports
        data = {
            "metadata": meta,
            "observations": [observation],
            "assertions": [assertion],
            "subreports": reports,
        }
        return seal_run(tmp_path / f"run-{counter}", data)

    return make


def keys(*runs):
    return {run["metadata"]["mode"]: run["metadata"]["expected_keys"] for run in runs}


def gate(kind, runs, **kwargs):
    return evaluate_gate(
        kind,
        runs,
        candidate_sha=kwargs.pop("candidate_sha", "candidate"),
        expected_keys_by_mode=kwargs.pop("expected_keys_by_mode", keys(*runs)),
        **kwargs,
    )


def issue_for(run, **changes):
    row = run["assertions"][0]
    issue = {
        name: row[name]
        for name in (
            "mode",
            "case_id",
            "probe_id",
            "checkpoint",
            "assertion_id",
            "failure_type",
            "severity",
        )
    }
    issue.update(issue_id="known-1", status="open", resolved_commit=None)
    issue.update(changes)
    return issue


def baseline(run, identifier="accepted-1"):
    return {"acceptance_id": identifier, "run": run}


def trust_baseline(record, issues=None):
    return {
        "accepted_baselines": {record["acceptance_id"]: record["run"]["manifest_hash"]},
        "latest_accepted_baselines": {record["run"]["metadata"]["mode"]: record["acceptance_id"]},
        "known_issues_hash": object_hash(issues or []),
    }


def review_for(run, **changes):
    value = {
        "review_id": "review-1",
        "run_manifest_hash": run["manifest_hash"],
        "key": run["metadata"]["expected_keys"][0],
        "output_hash": run["assertions"][0]["observation_hash"],
        "rubric_hash": "rubric",
        "verdict": "pass",
        "reviewer": "reviewer-a",
        "role": "sales",
        "reason": "Verified against the supplied evidence.",
        "reviewed_at": "2026-10-04T00:00:00Z",
    }
    value.update(changes)
    return value


def review_context(reviews):
    fixed = {"review_set_id": "review-set-1", "reviews": reviews}
    return fixed, {"accepted_review_set_hashes": [object_hash(fixed)]}


def provenance_for(run, **changes):
    value = {
        "repository": "owner/project",
        "tested_commit": run["metadata"]["tested_commit"],
        "workflow_sha": "workflow",
        "run_id": 123,
        "attempt": 1,
        "artifact_id": 456,
        "artifact_digest": "sha256:artifact",
        "manifest_hash": run["manifest_hash"],
    }
    value.update(changes)
    return value


def approval_for(run, previous=None, issues=None, review_set=None):
    binding = {
        "tested_commit": run["metadata"]["tested_commit"],
        "manifest_hash": run["manifest_hash"],
        "review_set_hash": object_hash(review_set or EMPTY_REVIEW_SET),
        "previous_acceptance_id": previous["acceptance_id"] if previous else None,
        "known_issues_hash": object_hash(issues or []),
    }
    return {"approval_ref": "reviewed-git-commit", "acceptance_id": "new-acceptance"}, {
        "latest_accepted_baselines": {},
        "approval_bindings": {"reviewed-git-commit": binding},
    }


def resign(root):
    manifest = read_json(root / "manifest.json")
    for name in manifest["files"]:
        path = root / name
        manifest["files"][name] = {"sha256": file_hash(path), "size": path.stat().st_size}
    (root / "manifest.json").write_bytes(json_bytes(manifest))
    (root / "COMPLETED").write_bytes(
        json_bytes({"manifest_sha256": file_hash(root / "manifest.json")})
    )


def test_seal_roundtrip_append_only_and_external_key_set(factory, tmp_path):
    run = factory(behavior="fail")
    assert load_run(run["directory"], expected_keys=run["metadata"]["expected_keys"]) == run
    with pytest.raises(FileExistsError):
        seal_run(run["directory"], run)
    write_record(tmp_path / "reviews" / "one.json", {"review": 1})
    with pytest.raises(FileExistsError):
        write_record(tmp_path / "reviews" / "one.json", {"review": 2})
    with pytest.raises(QualityReportError):
        load_run(run["directory"], expected_keys=[["x"] * 6])
    assert object_hash({"b": 2, "a": 1}) == object_hash({"a": 1, "b": 2})
    with pytest.raises(ValueError):
        object_hash(float("nan"))


@pytest.mark.parametrize(
    "change",
    [
        "file",
        "marker",
        "extra",
        "missing",
        "manifest",
        "metadata",
        "files",
        "duplicate_subreport",
        "bad_index",
        "empty_keys",
        "duplicate_key",
        "unknown_key",
        "bad_observation",
        "missing_observation",
        "jsonl_array",
        "broken_jsonl",
        "duplicate_json",
    ],
)
def test_storage_rejects_corrupt_or_incomplete_reports(factory, change):
    run = factory()
    root = Path(run["directory"])
    if change == "file":
        (root / "assertions.jsonl").write_text("tampered", encoding="utf-8")
    elif change == "marker":
        (root / "COMPLETED").write_text("{}", encoding="utf-8")
    elif change == "extra":
        (root / "extra").write_text("extra", encoding="utf-8")
    elif change == "missing":
        (root / "COMPLETED").unlink()
    elif change in {
        "manifest",
        "metadata",
        "files",
        "duplicate_subreport",
        "bad_index",
        "empty_keys",
    }:
        manifest = read_json(root / "manifest.json")
        if change == "manifest":
            manifest["state"] = "running"
        elif change == "metadata":
            manifest["metadata"] = []
        elif change == "files":
            manifest["files"].pop("summary.md")
        elif change == "duplicate_subreport":
            manifest["subreport_names"] = ["x", "x"]
        elif change == "bad_index":
            manifest["files"]["summary.md"] = None
        else:
            manifest["metadata"]["expected_keys"] = []
        (root / "manifest.json").write_bytes(json_bytes(manifest))
        (root / "COMPLETED").write_bytes(
            json_bytes({"manifest_sha256": file_hash(root / "manifest.json")})
        )
    else:
        row = run["assertions"][0]
        if change == "duplicate_key":
            data = json.dumps(row) + "\n" + json.dumps(row)
        elif change == "jsonl_array":
            data = "[]"
        elif change == "broken_jsonl":
            data = "{"
        elif change == "duplicate_json":
            data = '{"mode":"mocked_model","mode":"mocked_model"}'
        else:
            row[
                {
                    "unknown_key": "assertion_id",
                    "bad_observation": "observation_hash",
                    "missing_observation": "observation_hash",
                }[change]
            ] = None if change == "missing_observation" else "changed"
            data = json.dumps(row)
        (root / "assertions.jsonl").write_text(data, encoding="utf-8")
        resign(root)
    with pytest.raises(QualityReportError):
        load_run(root)


@pytest.mark.parametrize("parts", [[], ["x"] * 5, ["x"] * 5 + [1], ["x"] * 5 + [""]])
def test_invalid_keys(parts):
    with pytest.raises(QualityReportError):
        assertion_key(parts)


@pytest.mark.parametrize(
    "change",
    [
        "empty",
        "meta_mismatch",
        "wrong_mode",
        "bad_execution",
        "missing_behavior",
        "error_behavior",
        "not_applicable",
        "automatic_review",
        "bad_subreport",
    ],
)
def test_seal_rejects_invalid_contract_before_acceptance(factory, tmp_path, change):
    data = factory()
    expected = data["metadata"]["expected_keys"]
    row = data["assertions"][0]
    if change == "empty":
        expected = []
    elif change == "meta_mismatch":
        expected = [["other"] * 6]
    elif change == "wrong_mode":
        data["metadata"]["mode"] = "live"
    elif change == "bad_execution":
        row["execution_status"] = "success"
    elif change == "missing_behavior":
        row["behavior_status"] = None
    elif change == "error_behavior":
        row["execution_status"] = "error"
    elif change == "not_applicable":
        row.update(execution_status="not_applicable", behavior_status=None)
    elif change == "automatic_review":
        row["behavior_status"] = "needs_review"
    else:
        data["subreports"] = {"../outside": {}}
    with pytest.raises(QualityReportError):
        seal_run(tmp_path / "invalid", data, expected_keys=expected)


def test_json_and_file_safety(tmp_path):
    for name in ("../outside", "dir/file", "dir\\file", "", 7):
        with pytest.raises(QualityReportError):
            _checked_file(tmp_path, name)
    with pytest.raises(QualityReportError):
        read_json(tmp_path / "absent.json")
    with pytest.raises(QualityReportError):
        _read_lines(tmp_path / "absent.jsonl")
    path = tmp_path / "bad.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(QualityReportError):
        read_json(path)
    with pytest.raises(QualityReportError):
        key_set([["x"] * 6, ["x"] * 6])


def test_inventory_preserves_business_failures_and_provisional_status(factory):
    for behavior in ("pass", "fail", "needs_review"):
        result = gate("inventory", [factory(behavior=behavior, metadata={"provisional": True})])
        assert result["exit_code"] == 0
        assert result["suite_release_status"] == "not_evaluated"
        assert result["product_release_status"] == "not_evaluated"
        assert result["provisional"] is True
    assert gate("inventory", [factory(execution="error")])["exit_code"] == 2
    assert gate("inventory", [factory(mode="rule_only")])["exit_code"] == 0
    assert gate("inventory", [factory(mode="rule_only", subreports={})])["exit_code"] == 2


def test_all_failure_reasons_survive_priority_and_release_stays_scoped(factory):
    first = factory(behavior="fail")
    second = factory(mode="live", execution="not_run")
    result = gate("release", [first, second])
    assert result["exit_code"] == 3
    assert {row["exit_code"] for row in result["reasons"]} == {1, 2, 3}
    assert result["suite_release_status"] == "blocked"
    assert result["product_release_status"] == "not_evaluated"


@pytest.mark.parametrize(
    "change",
    [
        "missing_sha",
        "wrong_sha",
        "unknown_mode",
        "duplicate",
        "missing_fingerprint",
        "altered_reference",
        "no_runs",
        "wrong_gate",
    ],
)
def test_gate_input_validation(factory, change):
    run = factory(metadata={"suite_hash": ""} if change == "missing_fingerprint" else {})
    kwargs = {}
    mode, reports = "inventory", [run]
    if change == "missing_sha":
        kwargs["candidate_sha"] = ""
    elif change == "wrong_sha":
        kwargs["candidate_sha"] = "other"
    elif change == "unknown_mode":
        kwargs["expected_keys_by_mode"] = {}
    elif change == "duplicate":
        reports.append(run)
    elif change == "altered_reference":
        run["manifest_hash"] = "fake"
    elif change == "no_runs":
        reports = []
    elif change == "wrong_gate":
        mode = "unknown"
    assert gate(mode, reports, **kwargs)["exit_code"] == (
        2 if change in {"no_runs", "wrong_gate"} else 3
    )


def test_regression_requires_precise_open_issue_and_never_waives_recurrence(factory):
    before = factory(behavior="fail")
    after = factory(behavior="fail")
    record = baseline(before)
    issue = issue_for(before)
    trust = trust_baseline(record, [issue])
    kwargs = {
        "baselines": {"mocked_model": record},
        "known_issues": [issue],
        "trust_context": trust,
    }
    assert gate("regression", [after], **kwargs)["exit_code"] == 0
    for changed in (
        dict(issue, failure_type="different"),
        dict(issue, severity="minor"),
        dict(issue, status="resolved", resolved_commit="fix"),
    ):
        changed_trust = dict(trust, known_issues_hash=object_hash([changed]))
        assert (
            gate(
                "regression",
                [after],
                baselines=kwargs["baselines"],
                known_issues=[changed],
                trust_context=changed_trust,
            )["exit_code"]
            == 1
        )
    good = factory()
    record = baseline(good)
    trust = trust_baseline(record, [issue])
    for candidate in (after, factory(behavior="needs_review"), factory(execution="error")):
        assert (
            gate(
                "regression",
                [candidate],
                baselines={"mocked_model": record},
                known_issues=[issue],
                trust_context=trust,
            )["exit_code"]
            != 0
        )


@pytest.mark.parametrize(
    "change",
    [
        "no_baseline",
        "untrusted",
        "untrusted_issue",
        "fingerprint",
        "pending_baseline",
        "incomplete_baseline",
        "bad_issue",
        "bad_signature",
        "resolved_without_commit",
        "duplicate_issue",
    ],
)
def test_regression_rejects_invalid_trust_and_baselines(factory, change):
    before = factory(
        behavior="needs_review" if change == "pending_baseline" else "fail",
        execution="error" if change == "incomplete_baseline" else "completed",
    )
    after = factory(metadata={"knowledge_hash": "different"} if change == "fingerprint" else {})
    record = baseline(before)
    issue = issue_for(factory(behavior="fail"))
    if change == "bad_issue":
        issue["status"] = "unknown"
    elif change == "bad_signature":
        issue["failure_type"] = None
    elif change == "resolved_without_commit":
        issue["status"] = "resolved"
    issues = [issue, issue] if change == "duplicate_issue" else [issue]
    trust = trust_baseline(record, issues)
    if change == "untrusted":
        trust["accepted_baselines"] = {}
    if change == "untrusted_issue":
        trust["known_issues_hash"] = "fake"
    baselines = {} if change == "no_baseline" else {"mocked_model": record}
    assert (
        gate("regression", [after], baselines=baselines, known_issues=issues, trust_context=trust)[
            "exit_code"
        ]
        == 3
    )


def test_dual_baselines_display_cumulative_and_latest_changes(factory, tmp_path):
    initial, previous, current = factory(behavior="fail"), factory(), factory()
    initial_record = baseline(initial, "initial")
    previous_record = baseline(previous, "latest")
    previous_record["initial_baseline"] = initial_record
    trust = trust_baseline(previous_record)
    trust["accepted_baselines"]["initial"] = initial["manifest_hash"]
    result = gate(
        "regression", [current], baselines={"mocked_model": previous_record}, trust_context=trust
    )
    assert result["exit_code"] == 0
    assert result["comparison"]["mocked_model"]["changes"] == []
    assert result["comparison"]["mocked_model"]["initial_changes"][0]["before"] == "fail"
    write_decision(tmp_path / "dual-comparison", result)


def test_reviews_can_complete_release_without_changing_sealed_evidence(factory, tmp_path):
    runs = [factory(mode="rule_only"), factory(), factory(mode="live", behavior="needs_review")]
    live = runs[-1]
    original = Path(live["directory"], "assertions.jsonl").read_bytes()
    fixed, trust = review_context([review_for(live)])
    record = baseline(runs[0])
    trust.update(trust_baseline(record))
    provenance = [provenance_for(run) for run in runs]
    trust["verified_artifacts"] = provenance
    kwargs = {"baselines": {"rule_only": record}, "trust_context": trust, "provenance": provenance}
    blocked = gate("release", runs, **kwargs)
    assert blocked["exit_code"] == 1
    accepted = gate("release", runs, review_set=fixed, **kwargs)
    assert accepted["exit_code"] == 0
    assert accepted["suite_release_status"] == "passed"
    assert accepted["product_release_status"] == "not_evaluated"
    assert Path(live["directory"], "assertions.jsonl").read_bytes() == original
    assert load_run(live["directory"])["assertions"][0]["behavior_status"] == "needs_review"
    write_decision(tmp_path / "blocked", blocked)
    write_decision(tmp_path / "accepted", accepted)
    with pytest.raises(FileExistsError):
        write_decision(tmp_path / "blocked", accepted)
    assert read_json(tmp_path / "blocked" / "decision.json")["exit_code"] == 1


@pytest.mark.parametrize(
    "change",
    [
        "untrusted",
        "bad_set",
        "missing_audit",
        "duplicate",
        "bad_verdict",
        "bad_key",
        "bad_output",
        "bad_rubric",
        "automatic",
        "automatic_fail",
        "unexecuted",
        "bad_supersedes",
        "self_supersedes",
        "cross_run",
        "cycle",
    ],
)
def test_reviews_cannot_override_automatic_checks_or_escape_binding(factory, change):
    run = (
        factory(
            behavior="fail" if change == "automatic_fail" else "needs_review",
            execution="error" if change == "unexecuted" else "completed",
            row={"manual_review": True} if change == "automatic_fail" else {},
        )
        if change != "automatic"
        else factory()
    )
    review = review_for(run)
    reviews = [review]
    if change == "missing_audit":
        review.pop("reason")
    elif change == "duplicate":
        reviews.append(deepcopy(review))
    elif change == "bad_verdict":
        review["verdict"] = "good"
    elif change == "bad_key":
        review["key"][-2] = "other"
    elif change == "bad_output":
        review["output_hash"] = "fake"
    elif change == "bad_rubric":
        review["rubric_hash"] = "fake"
    elif change in {"bad_supersedes", "self_supersedes", "cycle", "cross_run"}:
        review["supersedes_review_id"] = "review-1" if change == "self_supersedes" else "review-2"
        if change in {"cycle", "cross_run"}:
            second = dict(review, review_id="review-2", supersedes_review_id="review-1")
            if change == "cross_run":
                second["run_manifest_hash"] = "other"
            reviews.append(second)
    fixed, trust = review_context(reviews)
    if change == "bad_set":
        fixed.pop("review_set_id")
    if change == "untrusted":
        trust = {}
    with pytest.raises(QualityReportError):
        effective_assertions(run, fixed, trust)


def test_conflicts_and_role_coverage_stay_pending_until_explicit_correction(factory):
    run = factory(
        behavior="needs_review", metadata={"review_required_roles": ["sales", "developer"]}
    )
    one = review_for(run)
    fixed, trust = review_context([one])
    assert effective_assertions(run, fixed, trust)[0][0]["behavior_status"] == "needs_review"
    two = review_for(
        run, review_id="review-2", reviewer="reviewer-b", role="developer", verdict="fail"
    )
    fixed, trust = review_context([one, two])
    assert effective_assertions(run, fixed, trust)[0][0]["behavior_status"] == "needs_review"
    three = review_for(
        run,
        review_id="review-3",
        reviewer="reviewer-b",
        role="developer",
        supersedes_review_id="review-2",
    )
    unrelated = review_for(run, review_id="other-run", run_manifest_hash="different")
    fixed, trust = review_context([one, two, three, unrelated])
    rows, _, used = effective_assertions(run, fixed, trust)
    assert rows[0]["behavior_status"] == "pass"
    assert rows[0]["review_ids"] == ["review-1", "review-3"]
    assert "other-run" not in used


@pytest.mark.parametrize("change", ["missing", "duplicate", "field", "commit", "unverified"])
def test_artifact_provenance_must_match_external_provider(factory, change):
    run = factory()
    record = provenance_for(run)
    supplied, trust = [record], {"verified_artifacts": [deepcopy(record)]}
    if change == "missing":
        supplied = []
    elif change == "duplicate":
        supplied.append(record)
    elif change == "field":
        record.pop("artifact_id")
    elif change == "commit":
        record["tested_commit"] = "other"
    else:
        trust = {"trusted": True}
    with pytest.raises(QualityReportError):
        verify_provenance(run, supplied, trust)


@pytest.mark.parametrize(
    "change",
    [
        "provisional",
        "missing",
        "invalid_contract",
        "contract_fail",
        "retrieval_fail",
        "retrieval_invalid",
        "baseline_no_retrieval",
    ],
)
def test_release_subreport_and_nonprovisional_requirements(factory, change):
    before = factory(mode="rule_only")
    reports = deepcopy(before["subreports"])
    if change == "missing":
        reports.pop("retrieval-v4")
    elif change == "invalid_contract":
        reports["recommendation-contract"]["case_count"] = 11
    elif change == "contract_fail":
        reports["recommendation-contract"]["checks"][0]["pass"] = False
    elif change == "retrieval_fail":
        reports["retrieval-v4"]["evaluations"]["raw_query"]["cases"][0]["unjudged_rate_at_3"] = 1
    elif change == "retrieval_invalid":
        reports["retrieval-v4"]["report_schema_version"] = "v3"
    if change == "baseline_no_retrieval":
        before = factory(mode="rule_only", subreports={})
    after = factory(
        mode="rule_only", subreports=reports, metadata={"provisional": change == "provisional"}
    )
    record = baseline(before)
    trust = trust_baseline(record)
    trust["require_provenance"] = False
    provenance = [provenance_for(after)]
    trust["verified_artifacts"] = provenance
    result = gate(
        "release",
        [after],
        baselines={"rule_only": record},
        trust_context=trust,
        required_modes=["rule_only"],
        provenance=provenance,
    )
    expected = (
        2 if change == "missing" else 1 if change in {"contract_fail", "retrieval_fail"} else 3
    )
    assert result["exit_code"] == expected


def test_bootstrap_advancement_resolves_issues_atomically_and_blocks_recurrence(factory):
    failed = factory(behavior="fail")
    issue = issue_for(failed)
    approval, trust = approval_for(failed, issues=[issue])
    first = accept_baseline(
        failed, previous=None, known_issues=[issue], approval=approval, trust_context=trust
    )
    assert first["initial_acceptance_id"] == first["acceptance_id"]
    assert first["known_issues"][0]["status"] == "open"
    passed = factory()
    approval, new_trust = approval_for(passed, previous=first, issues=[issue])
    approval["acceptance_id"] = "second"
    new_trust.update(trust_baseline(first, [issue]))
    second = accept_baseline(
        passed, previous=first, known_issues=[issue], approval=approval, trust_context=new_trust
    )
    assert second["initial_acceptance_id"] == first["acceptance_id"]
    assert second["initial_baseline"]["manifest_hash"] == first["manifest_hash"]
    assert second["known_issues"][0]["status"] == "resolved"
    assert second["known_issues"][0]["resolved_commit"] == "candidate"
    assert first["known_issues"][0]["status"] == "open"
    recur = factory(behavior="fail")
    trusted = trust_baseline(second, [issue])
    trusted["accepted_baselines"][first["acceptance_id"]] = first["manifest_hash"]
    result = gate(
        "regression",
        [recur],
        baselines={"mocked_model": second},
        known_issues=[issue],
        trust_context=trusted,
    )
    assert result["exit_code"] == 1


@pytest.mark.parametrize(
    "change",
    [
        "dirty",
        "draft",
        "provisional",
        "stale",
        "missing_approval",
        "pending",
        "unexecuted",
        "unregistered",
        "regression",
    ],
)
def test_baseline_acceptance_rejects_unapproved_or_incomplete_evidence(factory, change):
    metadata = (
        {"source_dirty": True}
        if change == "dirty"
        else {"business_labels_reviewed": False}
        if change == "draft"
        else {"provisional": True}
        if change == "provisional"
        else {}
    )
    run = factory(
        behavior="needs_review"
        if change == "pending"
        else "fail"
        if change in {"unregistered", "regression"}
        else "pass",
        execution="error" if change == "unexecuted" else "completed",
        metadata=metadata,
    )
    previous = baseline(factory()) if change == "regression" else None
    issues = [issue_for(run)] if change == "regression" else []
    approval, trust = approval_for(run, previous=previous, issues=issues)
    if previous:
        trust.update(trust_baseline(previous, issues))
    if change == "stale":
        trust["latest_accepted_baselines"] = {"mocked_model": "already-initialized"}
    if change == "missing_approval":
        trust["approval_bindings"] = {}
    with pytest.raises(QualityReportError):
        accept_baseline(
            run, previous=previous, known_issues=issues, approval=approval, trust_context=trust
        )


def test_custom_summary_and_exact_observation_binding(factory, tmp_path):
    data = factory()
    data["summary"] = "本套件没有代表整个产品已通过验收。"
    custom = seal_run(tmp_path / "custom-summary", data)
    assert Path(custom["directory"], "summary.md").read_text(encoding="utf-8") == data["summary"]
    data["summary"] = {}
    with pytest.raises(QualityReportError, match="summary must be text"):
        seal_run(tmp_path / "invalid-summary", data)
    data.pop("summary")
    data["observations"][0]["trial_id"] = "2"
    data["assertions"][0]["observation_hash"] = object_hash(data["observations"][0])
    with pytest.raises(QualityReportError, match="different checkpoint or trial"):
        seal_run(tmp_path / "wrong-observation", data)


def test_equal_hashes_do_not_substitute_for_equal_assertion_sets(factory):
    before = factory()
    after = factory(row={"assertion_id": "another-assertion"})
    record = baseline(before)
    result = gate(
        "regression",
        [after],
        baselines={"mocked_model": record},
        trust_context=trust_baseline(record),
    )
    assert result["exit_code"] == 3
    assert any("coverage differs" in reason["message"] for reason in result["reasons"])


@pytest.mark.parametrize("field", ["suite_hash", "environment_hash"])
def test_release_rejects_mixed_protocol_even_with_verified_artifacts(factory, field):
    runs = [
        factory(mode="rule_only"),
        factory(metadata={field: "different"}),
        factory(mode="live"),
    ]
    record = baseline(runs[0])
    trust = trust_baseline(record)
    provenance = [provenance_for(run) for run in runs]
    trust["verified_artifacts"] = provenance
    result = gate(
        "release", runs, baselines={"rule_only": record}, provenance=provenance, trust_context=trust
    )
    assert result["exit_code"] == 3
    assert any("different protocols" in reason["message"] for reason in result["reasons"])


def test_human_failure_gets_a_precise_signature_for_known_issue_registration(factory):
    run = factory(behavior="needs_review")
    fixed, trust = review_context(
        [review_for(run, verdict="fail", failure_type="unsupported_promise")]
    )
    rows, _, _ = effective_assertions(run, fixed, trust)
    assert rows[0]["behavior_status"] == "fail"
    assert rows[0]["failure_type"] == "unsupported_promise"
    fixed, trust = review_context([review_for(run, verdict="fail", failure_type="")])
    with pytest.raises(QualityReportError, match="failure signature"):
        effective_assertions(run, fixed, trust)


def test_historical_baseline_cannot_be_selected_to_hide_recurrence(factory):
    old = factory(behavior="fail")
    candidate = factory(behavior="fail")
    record = baseline(old, "old-accepted")
    issue = issue_for(old)
    trust = trust_baseline(record, [issue])
    trust["latest_accepted_baselines"]["mocked_model"] = "new-fixed-version"
    result = gate(
        "regression",
        [candidate],
        baselines={"mocked_model": record},
        known_issues=[issue],
        trust_context=trust,
    )
    assert result["exit_code"] == 3
    assert any("latest accepted" in row["message"] for row in result["reasons"])


def test_bootstrap_requires_explicit_verified_empty_index(factory):
    run = factory()
    approval, trust = approval_for(run)
    trust.pop("latest_accepted_baselines")
    with pytest.raises(QualityReportError, match="explicit verified"):
        accept_baseline(run, previous=None, known_issues=[], approval=approval, trust_context=trust)


def test_acceptance_ids_cannot_be_reused(factory):
    run = factory()
    approval, trust = approval_for(run)
    trust["accepted_baselines"] = {approval["acceptance_id"]: "old-manifest"}
    with pytest.raises(QualityReportError, match="cannot be reused"):
        accept_baseline(run, previous=None, known_issues=[], approval=approval, trust_context=trust)


@pytest.mark.parametrize("developer_identity", ["reviewer-a", " REVIEWER-A "])
def test_one_person_cannot_satisfy_both_review_roles(factory, developer_identity):
    run = factory(
        behavior="needs_review", metadata={"review_required_roles": ["developer", "sales"]}
    )
    fixed, trust = review_context(
        [
            review_for(run, role="sales", reviewer="reviewer-a"),
            review_for(run, review_id="review-2", role="developer", reviewer=developer_identity),
        ]
    )
    rows, _, _ = effective_assertions(run, fixed, trust)
    assert rows[0]["behavior_status"] == "needs_review"
    assert run["assertions"][0]["behavior_status"] == "needs_review"


def test_two_people_with_the_same_role_do_not_replace_the_missing_role(factory):
    run = factory(
        behavior="needs_review", metadata={"review_required_roles": ["developer", "sales"]}
    )
    fixed, trust = review_context(
        [
            review_for(run, role="sales", reviewer="reviewer-a"),
            review_for(run, review_id="review-2", role="sales", reviewer="reviewer-b"),
        ]
    )
    assert effective_assertions(run, fixed, trust)[0][0]["behavior_status"] == "needs_review"


def test_dual_role_policy_does_not_require_review_for_automatic_verdicts(factory):
    for behavior in ("pass", "fail"):
        run = factory(behavior=behavior, metadata={"review_required_roles": ["developer", "sales"]})
        rows, _, _ = effective_assertions(run, EMPTY_REVIEW_SET, {})
        assert rows[0]["behavior_status"] == behavior
