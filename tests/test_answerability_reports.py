"""Adversarial evidence, review, regression, and acceptance tests (no real APIs)."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lead_cleaner.answerability_evaluation import gates, provenance, reports, trust

SHA = "a" * 40
REFERENCE = "b" * 40


def raw(
    mode: str = "rule_only", status: str = "pass", *, provisional: bool = False
) -> dict[str, Any]:
    observation = {
        "protocol_id": "p0-02.v1",
        "mode": mode,
        "case_id": "AB01",
        "probe_id": "conversation",
        "turn_id": "T1",
        "trial_id": "1",
        "execution_status": "completed",
        "reply_text": "confirmed",
        "provided_context": [],
    }
    assertion = {
        **{f: observation[f] for f in reports.OBSERVATION_FIELDS},
        "assertion_id": "test_contract",
        "execution_status": "completed",
        "behavior_status": status,
        "failure_type": "unsupported" if status == "fail" else None,
        "severity": "critical",
        "mandatory": True,
        "manual_review": status == "needs_review",
        "observation_hash": reports.content_hash(observation),
    }
    metric = {"applicability": "applicable", "numerator": 1, "denominator": 1, "value": 1.0}
    retrieval = (
        [
            {
                "case_id": "AB01",
                "path": "raw_query",
                "query": "question",
                "execution_status": "completed",
                "metrics": {
                    name: dict(metric, value=0.0 if name == "unjudged_rate" else 1.0)
                    for name in reports.METRICS
                },
            }
        ]
        if mode == "rule_only"
        else []
    )
    metadata = {
        "schema_version": "answerability-eval.v1",
        "protocol_id": "p0-02.v1",
        "mode": mode,
        "tested_commit": SHA,
        "protocol_hash": "protocol",
        "dataset_hash": "dataset",
        "knowledge_hash": "knowledge",
        "evaluator_hash": "evaluator",
        "rubric_hash": "rubric",
        "environment_hash": "environment",
        "code_hash": "code",
        "real_model_calls": 0,
        "provisional": provisional,
        "source_dirty": False,
        "business_labels_reviewed": True,
        "expected_keys": [list(reports.key(assertion))],
        "expected_retrieval_keys": [[r["case_id"], r["path"]] for r in retrieval],
        "review_required_roles": ["developer", "sales"],
    }
    return {
        "metadata": metadata,
        "observations": [observation],
        "assertions": [assertion],
        "retrieval": retrieval,
        "metrics": {"diagnostic": "not a total accuracy"},
    }


@pytest.fixture
def make(tmp_path):
    count = 0

    def create(data=None, **kwargs):
        nonlocal count
        count += 1
        return reports.seal_run(tmp_path / f"report-{count}", data or raw(**kwargs))

    return create


def issue(run):
    row = run["assertions"][0]
    return {"issue_id": "P002-001", "status": "open", **{f: row[f] for f in gates.ISSUE_FIELDS}}


def artifact(run):
    return {
        "repository": "owner/repo",
        "tested_commit": run["metadata"]["tested_commit"],
        "workflow_sha": run["metadata"]["tested_commit"],
        "run_id": "1",
        "attempt": "1",
        "artifact_id": "2",
        "artifact_digest": "digest",
        "manifest_hash": run["manifest_hash"],
    }


def trusted(run, issues=None, previous=None):
    issues = issues or []
    value = {
        "protocol_id": "p0-02.v1",
        "accepted_baselines": {},
        "latest_accepted_baselines": {},
        "accepted_review_set_hashes": [],
        "approval_bindings": {},
        "known_issues_hash": reports.content_hash(issues),
        "verified_artifacts": [artifact(run)],
    }
    if previous:
        value["accepted_baselines"][previous["acceptance_id"]] = previous["run"]["manifest_hash"]
        value["latest_accepted_baselines"][run["metadata"]["mode"]] = previous["acceptance_id"]
    return value


def authorize(run, context, issues=None, previous=None, review_set=None, identifier="accepted-1"):
    metadata = run["metadata"]
    binding = {
        "protocol_id": metadata["protocol_id"],
        "tested_commit": metadata["tested_commit"],
        "manifest_hash": run["manifest_hash"],
        "protocol_hash": metadata["protocol_hash"],
        "dataset_hash": metadata["dataset_hash"],
        "rubric_hash": metadata["rubric_hash"],
        "review_set_hash": reports.content_hash(review_set or trust.EMPTY_REVIEW_SET),
        "known_issues_hash": reports.content_hash(issues or []),
        "previous_acceptance_id": previous["acceptance_id"] if previous else None,
    }
    context["approval_bindings"][identifier] = binding
    return {"approval_ref": identifier, "acceptance_id": identifier}


def check(kind, run, **kwargs):
    metadata = run["metadata"]
    return gates.evaluate_gate(
        kind,
        [run],
        candidate_sha=kwargs.pop("candidate_sha", SHA),
        expected_keys_by_mode={metadata["mode"]: metadata["expected_keys"]},
        expected_retrieval_keys_by_mode={metadata["mode"]: metadata["expected_retrieval_keys"]},
        required_modes=kwargs.pop("required_modes", [metadata["mode"]]),
        **kwargs,
    )


def reviews_for(run, verdict="pass", reviewer="sales-person"):
    return {
        "review_set_id": "review-1",
        "reviews": [
            {
                "review_id": role,
                "key": list(reports.key(run["assertions"][0])),
                "run_manifest_hash": run["manifest_hash"],
                "output_hash": run["assertions"][0]["observation_hash"],
                "rubric_hash": "rubric",
                "reviewer": "developer-person" if role == "developer" else reviewer,
                "role": role,
                "reason": "Checked actual evidence",
                "reviewed_at": "2026-10-05T00:00:00Z",
                "verdict": verdict,
            }
            for role in ("developer", "sales")
        ],
    }


def test_raw_observations_precede_scoring_and_seal_is_immutable(tmp_path):
    data = raw()
    directory = reports.stage_observations(tmp_path / "staged", data["observations"])
    before = (directory / "observations.jsonl").read_bytes()
    run = reports.seal_run(directory, data)
    assert (directory / "observations.jsonl").read_bytes() == before
    assert reports.load_run(directory)["manifest_hash"] == run["manifest_hash"]
    with pytest.raises(reports.ReportError, match="exists"):
        reports.seal_run(directory, data)
    with pytest.raises(FileExistsError):
        reports.stage_observations(directory, data["observations"])


@pytest.mark.parametrize(
    "change", ["extra", "missing", "bytes", "completed", "manifest", "directory", "stage_digest"]
)
def test_tampered_report_is_rejected(make, change):
    run = make()
    path = Path(run["directory"])
    if change == "extra":
        (path / "unsealed.json").write_text("{}")
    elif change == "missing":
        (path / "metrics.json").unlink()
    elif change == "bytes":
        (path / "assertions.jsonl").write_bytes(b"changed")
    elif change == "completed":
        (path / "COMPLETED").write_text("forged")
    elif change == "manifest":
        (path / "manifest.json").write_text('{"storage_version":"old"}')
    elif change == "directory":
        (path / "metrics.json").unlink()
        (path / "metrics.json").mkdir()
    else:
        (path / "OBSERVATIONS").write_text("modified")
    with pytest.raises(reports.ReportError):
        reports.load_run(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "rag-eval-v4"),
        ("protocol_id", "p0-01.v1"),
        ("mode", "live"),
        ("environment_hash", ""),
        ("real_model_calls", 1),
    ],
)
def test_protocol_and_offline_boundary(make, field, value):
    data = raw()
    data["metadata"][field] = value
    with pytest.raises(reports.ReportError):
        make(data)


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "missing",
        "unknown",
        "obs_hash",
        "obs_identity",
        "status",
        "unexecuted_verdict",
        "severity",
        "review",
        "failure",
        "mode",
        "retrieval_missing",
        "retrieval_unknown",
        "metric_missing",
        "metric_status",
        "metric_range",
        "metric_nonfinite",
        "metric_na_value",
        "metric_negative",
        "metric_coverage",
    ],
)
def test_exact_suite_and_result_contract(make, change):
    data = raw()
    row = data["assertions"][0]
    metric = data["retrieval"][0]["metrics"]["ndcg"]
    if change == "duplicate":
        data["assertions"].append(dict(row))
    elif change == "missing":
        data["assertions"] = []
    elif change == "unknown":
        row["assertion_id"] = "another"
    elif change == "obs_hash":
        row["observation_hash"] = "fake"
    elif change == "obs_identity":
        data["observations"][0]["turn_id"] = "T3"
    elif change == "status":
        row["execution_status"] = "not_applicable"
    elif change == "unexecuted_verdict":
        row["execution_status"] = "error"
    elif change == "severity":
        row["severity"] = "low"
    elif change == "review":
        row["behavior_status"] = "needs_review"
    elif change == "failure":
        row["behavior_status"] = "fail"
    elif change == "mode":
        data["metadata"]["mode"] = "mocked_model"
    elif change == "retrieval_missing":
        data["retrieval"] = []
    elif change == "retrieval_unknown":
        data["retrieval"][0]["path"] = "invented"
    elif change == "metric_missing":
        del data["retrieval"][0]["metrics"]["ndcg"]
    elif change == "metric_status":
        metric["applicability"] = "unknown"
    elif change == "metric_range":
        metric["value"] = 2
    elif change == "metric_nonfinite":
        metric["value"] = float("nan")
    elif change == "metric_na_value":
        metric["applicability"] = "not_applicable"
    elif change == "metric_negative":
        metric["denominator"] = -1
    else:
        metric["error_count"] = -1
    with pytest.raises(reports.ReportError):
        make(data)


def test_external_keys_stage_changes_and_json_rejections(make, tmp_path):
    data = raw()
    with pytest.raises(reports.ReportError):
        reports.seal_run(tmp_path / "wrong", data, expected_keys=[])
    run = make()
    with pytest.raises(reports.ReportError):
        reports.load_run(run["directory"], expected_retrieval_keys=[])
    reports.stage_observations(tmp_path / "pending", data["observations"])
    (tmp_path / "pending" / "observations.jsonl").write_bytes(b"changed")
    with pytest.raises(reports.ReportError):
        reports.seal_run(tmp_path / "pending", data)
    for text in ('{"a":1,"a":2}', "NaN", "{"):
        with pytest.raises(reports.ReportError):
            reports.parse_json(text)
    with pytest.raises(reports.ReportError):
        reports.read_json(tmp_path / "missing")
    with pytest.raises(reports.ReportError):
        reports.key(["short"])
    with pytest.raises(reports.ReportError):
        reports.load_run(tmp_path / "missing")


def test_inventory_keeps_business_failure_and_review_separate(make, tmp_path):
    failed = make(status="fail")
    assert check("inventory", failed)["exit_code"] == 0
    reviewed = make(status="needs_review")
    assert check("inventory", reviewed)["exit_code"] == 0
    assert check("behavior", reviewed)["exit_code"] == 1
    assert check("behavior", failed)["suite_behavior_status"] == "blocked"
    decision = check("behavior", make())
    assert decision["exit_code"] == 0
    assert decision["product_release_status"] == "not_evaluated"
    path = gates.write_decision(tmp_path / "decision", decision)
    assert "真实模型未测" in (path / "summary.md").read_text("utf-8")
    with pytest.raises(FileExistsError):
        gates.write_decision(path, decision)


def test_error_priority_candidate_and_required_modes(make):
    data = raw()
    data["assertions"][0].update(execution_status="error", behavior_status=None)
    run = make(data)
    assert check("inventory", run)["exit_code"] == 2
    assert check("behavior", run, candidate_sha="another")["exit_code"] == 3
    assert (
        check("inventory", make(), required_modes=["rule_only", "mocked_model"])["exit_code"] == 2
    )
    assert check("invalid", make())["exit_code"] == 2
    assert check("inventory", make(), candidate_sha="")["exit_code"] == 3
    assert check("behavior", make(provisional=True))["exit_code"] == 3
    decision = gates.evaluate_gate(
        "behavior",
        [],
        candidate_sha=SHA,
        expected_keys_by_mode={},
        expected_retrieval_keys_by_mode={},
    )
    assert decision["exit_code"] == 2


def test_unknown_retrieval_is_not_a_complete_baseline(make):
    data = raw()
    data["retrieval"][0]["metrics"]["ndcg"].update(applicability="incomplete_judgments", value=None)
    run = make(data)
    assert check("inventory", run)["exit_code"] == 0
    assert check("behavior", run)["exit_code"] == 1
    context = trusted(run)
    approval = authorize(run, context)
    with pytest.raises(reports.ReportError, match="Unknown"):
        gates.accept_baseline(
            run, previous=None, known_issues=[], approval=approval, trust_context=context
        )
    data = raw()
    data["retrieval"][0]["execution_status"] = "not_run"
    assert check("inventory", make(data))["exit_code"] == 2
    data = raw()
    data["retrieval"][0]["metrics"]["ndcg"]["error_count"] = 1
    assert check("inventory", make(data))["exit_code"] == 2


def test_review_is_approved_bound_dual_identity_and_append_only(make):
    run = make(status="needs_review")
    review = reviews_for(run)
    context = trusted(run)
    with pytest.raises(reports.ReportError):
        trust.effective_assertions(run, review, context)
    context["accepted_review_set_hashes"] = [reports.content_hash(review)]
    rows, _, _ = trust.effective_assertions(run, review, context)
    assert rows[0]["behavior_status"] == "pass"
    assert reports.load_run(run["directory"])["assertions"][0]["behavior_status"] == "needs_review"
    same_person = reviews_for(run, reviewer=" DEVELOPER-person ")
    context["accepted_review_set_hashes"] = [reports.content_hash(same_person)]
    assert (
        trust.effective_assertions(run, same_person, context)[0][0]["behavior_status"]
        == "needs_review"
    )
    review["reviews"][1]["verdict"] = "fail"
    context["accepted_review_set_hashes"] = [reports.content_hash(review)]
    assert (
        trust.effective_assertions(run, review, context)[0][0]["behavior_status"] == "needs_review"
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "verdict",
        "hash",
        "rubric",
        "key",
        "automatic",
        "correction",
        "cycle",
        "roles",
        "failure_signatures",
    ],
)
def test_invalid_reviews_never_override_raw_results(make, change):
    run = make(status="fail" if change == "automatic" else "needs_review")
    review = reviews_for(run, verdict="fail" if change == "failure_signatures" else "pass")
    first = review["reviews"][0]
    if change == "missing":
        del first["reason"]
    elif change == "duplicate":
        review["reviews"].append(dict(first))
    elif change == "verdict":
        first["verdict"] = "accepted"
    elif change == "hash":
        first["output_hash"] = "wrong"
    elif change == "rubric":
        first["rubric_hash"] = "wrong"
    elif change == "key":
        first["key"] = []
    elif change == "correction":
        first["supersedes_review_id"] = "missing"
    elif change == "cycle":
        first["supersedes_review_id"] = first["review_id"]
    elif change == "roles":
        run["metadata"]["review_required_roles"] = []
    elif change == "failure_signatures":
        first["failure_type"] = "different"
    context = trusted(run)
    context["accepted_review_set_hashes"] = [reports.content_hash(review)]
    with pytest.raises(reports.ReportError):
        trust.effective_assertions(run, review, context)


def test_review_correction_other_manifest_and_failure_signature(make):
    run = make(status="needs_review")
    review = reviews_for(run, verdict="fail")
    context = trusted(run)
    context["accepted_review_set_hashes"] = [reports.content_hash(review)]
    assert (
        trust.effective_assertions(run, review, context)[0][0]["failure_type"]
        == "human_review_failure"
    )
    for original in list(review["reviews"]):
        review["reviews"].append(
            dict(
                original,
                review_id=original["review_id"] + "-new",
                supersedes_review_id=original["review_id"],
                verdict="pass",
            )
        )
    unrelated = dict(review["reviews"][0], review_id="other", run_manifest_hash="other-manifest")
    review["reviews"].append(unrelated)
    context["accepted_review_set_hashes"] = [reports.content_hash(review)]
    assert trust.effective_assertions(run, review, context)[0][0]["behavior_status"] == "pass"
    with pytest.raises(reports.ReportError):
        trust.effective_assertions(run, {"reviews": []}, context)


def test_bootstrap_and_rolling_baseline_preserve_initial_and_recurrence(make):
    failed = make(status="fail")
    issues = [issue(failed)]
    context = trusted(failed, issues)
    approval = authorize(failed, context, issues)
    first = gates.accept_baseline(
        failed, previous=None, known_issues=issues, approval=approval, trust_context=context
    )
    assert first["known_issues"][0]["status"] == "open"
    same = make(status="fail")
    context = trusted(same, issues, first)
    assert (
        check(
            "regression",
            same,
            baselines={"rule_only": first},
            known_issues=issues,
            trust_context=context,
        )["exit_code"]
        == 0
    )
    fixed = make()
    context = trusted(fixed, issues, first)
    second = gates.accept_baseline(
        fixed,
        previous=first,
        known_issues=issues,
        approval=authorize(fixed, context, issues, first, identifier="accepted-2"),
        trust_context=context,
    )
    assert second["initial_acceptance_id"] == first["acceptance_id"]
    assert second["known_issues"][0]["status"] == "resolved"
    assert second["known_issues"][0]["resolved_commit"] == SHA
    context = trusted(same, issues, second)
    context["accepted_baselines"][first["acceptance_id"]] = first["manifest_hash"]
    regression = check(
        "regression",
        same,
        baselines={"rule_only": second},
        known_issues=issues,
        trust_context=context,
    )
    assert regression["exit_code"] == 1
    assert regression["comparison"]["rule_only"]["initial_baseline"] == first["acceptance_id"]
    with pytest.raises(reports.ReportError, match="passing"):
        gates.accept_baseline(
            same,
            previous=second,
            known_issues=issues,
            approval=authorize(same, context, issues, second, identifier="accepted-3"),
            trust_context=context,
        )


@pytest.mark.parametrize(
    "change",
    [
        "provisional",
        "latest",
        "issues",
        "artifact",
        "approval",
        "unregistered",
        "reused",
        "pending",
        "error",
    ],
)
def test_invalid_acceptance_is_blocked(make, change):
    data = raw(
        status="fail"
        if change == "unregistered"
        else "needs_review"
        if change == "pending"
        else "pass",
        provisional=change == "provisional",
    )
    if change == "error":
        data["assertions"][0].update(execution_status="error", behavior_status=None)
    run = make(data)
    context = trusted(run)
    approval = authorize(run, context)
    if change == "latest":
        del context["latest_accepted_baselines"]
    elif change == "issues":
        context["known_issues_hash"] = "untrusted"
    elif change == "artifact":
        context["verified_artifacts"] = []
    elif change == "approval":
        context["approval_bindings"] = {}
    elif change == "reused":
        context["accepted_baselines"][approval["acceptance_id"]] = "anything"
    with pytest.raises(reports.ReportError):
        gates.accept_baseline(
            run, previous=None, known_issues=[], approval=approval, trust_context=context
        )


@pytest.mark.parametrize(
    "change,code",
    [
        ("new_failure", 1),
        ("retrieval_worse", 1),
        ("unjudged_worse", 1),
        ("query", 3),
        ("denominator", 3),
        ("applicability", 3),
        ("fingerprint", 3),
        ("latest", 3),
        ("manifest", 3),
        ("issues", 3),
        ("source", 3),
    ],
)
def test_regression_checks_each_query_and_trusted_reference(make, change, code):
    baseline = make()
    record = {"acceptance_id": "old", "run": baseline}
    data = raw()
    if change == "new_failure":
        data["assertions"][0].update(behavior_status="fail", failure_type="unsupported")
    elif change == "retrieval_worse":
        data["retrieval"][0]["metrics"]["ndcg"]["value"] = 0.5
    elif change == "unjudged_worse":
        data["retrieval"][0]["metrics"]["unjudged_rate"]["value"] = 0.5
    elif change == "query":
        data["retrieval"][0]["query"] = "changed query"
    elif change == "denominator":
        data["retrieval"][0]["metrics"]["ndcg"]["denominator"] = 2
    elif change == "applicability":
        data["retrieval"][0]["metrics"]["ndcg"].update(applicability="not_applicable", value=None)
    elif change == "fingerprint":
        data["metadata"]["knowledge_hash"] = "changed"
    candidate = make(data)
    context = trusted(candidate, previous=record)
    if change == "latest":
        context["latest_accepted_baselines"] = {}
    elif change == "manifest":
        context["accepted_baselines"] = {}
    elif change == "issues":
        context["known_issues_hash"] = "wrong"
    elif change == "source":
        candidate["manifest_hash"] = "forged"
    assert (
        check("regression", candidate, baselines={"rule_only": record}, trust_context=context)[
            "exit_code"
        ]
        == code
    )


def test_atomic_two_mode_acceptance_and_gate_duplicate_protection(make):
    runs = [make(), make(mode="mocked_model")]
    context = trusted(runs[0])
    context["verified_artifacts"].append(artifact(runs[1]))
    approvals = {
        r["metadata"]["mode"]: authorize(r, context, identifier=r["metadata"]["mode"]) for r in runs
    }
    bundle = gates.accept_baselines(
        runs, previous={}, known_issues=[], approvals=approvals, trust_context=context
    )
    assert set(bundle["initial"]) == {"rule_only", "mocked_model"}
    assert context["latest_accepted_baselines"] == {}
    expected = {r["metadata"]["mode"]: r["metadata"]["expected_keys"] for r in runs}
    retrieval = {r["metadata"]["mode"]: r["metadata"]["expected_retrieval_keys"] for r in runs}
    assert (
        gates.evaluate_gate(
            "behavior",
            runs,
            candidate_sha=SHA,
            expected_keys_by_mode=expected,
            expected_retrieval_keys_by_mode=retrieval,
        )["exit_code"]
        == 0
    )
    assert (
        gates.evaluate_gate(
            "inventory",
            [runs[0], runs[0]],
            candidate_sha=SHA,
            expected_keys_by_mode=expected,
            expected_retrieval_keys_by_mode=retrieval,
        )["exit_code"]
        == 3
    )
    with pytest.raises(reports.ReportError):
        gates.accept_baselines(
            runs[:1], previous={}, known_issues=[], approvals=approvals, trust_context=context
        )
    data = raw("mocked_model")
    data["metadata"]["environment_hash"] = "different"
    runs[1] = make(data)
    with pytest.raises(reports.ReportError):
        gates.accept_baselines(
            runs, previous={}, known_issues=[], approvals=approvals, trust_context=context
        )
    assert (
        gates.evaluate_gate(
            "inventory",
            runs,
            candidate_sha=SHA,
            expected_keys_by_mode=expected,
            expected_retrieval_keys_by_mode=retrieval,
        )["exit_code"]
        == 3
    )


def test_trust_paths_current_main_and_guard(monkeypatch, tmp_path):
    values = {trust.TRUST_PATH: {"protocol_id": "p0-02.v1"}, trust.ISSUES_PATH: {"issues": []}}

    def fake_git(root, *args):
        if args[0] == "rev-parse":
            return REFERENCE
        path = args[-1].split(":", 1)[1]
        return json.dumps(values[path]) if path in values else "print('guard checked')"

    monkeypatch.setattr(trust, "git", fake_git)
    context = trust.load_trust_context(tmp_path, REFERENCE)
    assert context["known_issues_hash"] == reports.content_hash([])
    with pytest.raises(reports.ReportError):
        trust.require_current_ref(tmp_path, SHA)
    for path in ("../bad", "C:/bad", "a\\b", "/bad", "", "a//b"):
        with pytest.raises(reports.ReportError):
            trust.safe_relative(path)
    values[trust.TRUST_PATH] = []
    with pytest.raises(reports.ReportError):
        trust.load_trust_context(tmp_path, REFERENCE)
    values[trust.TRUST_PATH] = {"protocol_id": "p0-01.v1"}
    with pytest.raises(reports.ReportError):
        trust.load_trust_context(tmp_path, REFERENCE)
    monkeypatch.setattr(
        trust.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="verified")
    )
    assert trust.verify_protected_files(tmp_path, REFERENCE)["guard_output"] == "verified"
    monkeypatch.setattr(
        trust.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=3, stdout="changed")
    )
    with pytest.raises(reports.ReportError):
        trust.verify_protected_files(tmp_path, REFERENCE)


def provider_fixture(run, monkeypatch):
    directory = Path(run["directory"])
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        for path in directory.iterdir():
            output.writestr("rule/" + path.name, path.read_bytes())
    zipped = archive.getvalue()
    digest = hashlib.sha256(zipped).hexdigest()
    entry = {
        "directory": str(directory),
        "artifact_prefix": "rule",
        "provenance": dict(artifact(run), artifact_digest="sha256:" + digest),
    }
    artifact_meta = {"expired": False, "workflow_run": {"id": 1}, "digest": "sha256:" + digest}
    run_meta = {
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "head_sha": SHA,
        "run_attempt": 1,
        "path": ".github/workflows/answerability-eval.yml",
    }
    policy = {
        "protocol_id": "p0-02.v1",
        "repository": "owner/repo",
        "approved_workflow_paths": [run_meta["path"]],
    }
    monkeypatch.setattr(provenance, "trusted_json", lambda *a: policy)
    monkeypatch.setattr(provenance, "git", lambda *a: "trusted workflow")
    payload = {
        "repos/owner/repo/actions/artifacts/2": json.dumps(artifact_meta).encode(),
        "repos/owner/repo/actions/runs/1": json.dumps(run_meta).encode(),
        f"repos/owner/repo/contents/{run_meta['path']}?ref={SHA}": json.dumps(
            {"content": base64.b64encode(b"trusted workflow").decode()}
        ).encode(),
        "repos/owner/repo/actions/artifacts/2/zip": zipped,
    }
    return entry, payload, policy


def test_real_provider_contract_checks_full_report_bytes(make, monkeypatch, tmp_path):
    run = make()
    entry, payload, _ = provider_fixture(run, monkeypatch)
    verified = provenance.verify_github_artifacts(
        tmp_path, REFERENCE, [entry], getter=payload.__getitem__
    )
    assert verified[0]["manifest_hash"] == run["manifest_hash"]
    assert (
        provenance.require_verified_artifact(run, {"verified_artifacts": verified}) == verified[0]
    )
    monkeypatch.setattr(
        provenance.subprocess, "run", lambda args, **kw: SimpleNamespace(stdout=payload[args[-1]])
    )
    assert provenance.verify_github_artifacts(tmp_path, REFERENCE, [entry]) == verified
    with pytest.raises(reports.ReportError):
        provenance.verify_github_artifacts(
            tmp_path, REFERENCE, [entry, entry], getter=payload.__getitem__
        )


@pytest.mark.parametrize(
    "change",
    [
        "protocol",
        "repository",
        "wrong_repo",
        "missing",
        "manifest",
        "id",
        "expired",
        "run_id",
        "pull_request",
        "failed",
        "sha",
        "attempt",
        "workflow_sha",
        "workflow",
        "source",
        "zip_digest",
        "api_digest",
        "zip_bytes",
        "zip_extra",
        "zip_duplicate",
        "zip_unsafe",
        "zip_invalid",
    ],
)
def test_forged_provider_evidence_is_rejected(make, monkeypatch, tmp_path, change):
    run = make()
    entry, payload, policy = provider_fixture(run, monkeypatch)
    artifact_path = "repos/owner/repo/actions/artifacts/2"
    run_path = "repos/owner/repo/actions/runs/1"
    zip_path = artifact_path + "/zip"
    meta = json.loads(payload[artifact_path])
    workflow = json.loads(payload[run_path])
    if change == "protocol":
        policy["protocol_id"] = "p0-01.v1"
    elif change == "repository":
        policy["repository"] = "../bad"
    elif change == "wrong_repo":
        entry["provenance"]["repository"] = "fork/repo"
    elif change == "missing":
        del entry["provenance"]["attempt"]
    elif change == "manifest":
        entry["provenance"]["manifest_hash"] = "wrong"
    elif change == "id":
        entry["provenance"]["artifact_id"] = 0
    elif change == "expired":
        meta["expired"] = True
    elif change == "run_id":
        meta["workflow_run"]["id"] = 99
    elif change == "pull_request":
        workflow["event"] = "pull_request"
    elif change == "failed":
        workflow["conclusion"] = "failure"
    elif change == "sha":
        workflow["head_sha"] = REFERENCE
    elif change == "attempt":
        workflow["run_attempt"] = 2
    elif change == "workflow_sha":
        entry["provenance"]["workflow_sha"] = REFERENCE
    elif change == "workflow":
        policy["approved_workflow_paths"] = []
    elif change == "source":
        monkeypatch.setattr(provenance, "git", lambda *a: "changed workflow")
    elif change == "zip_digest":
        entry["provenance"]["artifact_digest"] = "wrong"
    elif change == "api_digest":
        meta["digest"] = "wrong"
    else:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for p in Path(run["directory"]).iterdir():
                archive.writestr(
                    "rule/" + p.name,
                    b"wrong"
                    if change == "zip_bytes" and p.name == "summary.md"
                    else p.read_bytes(),
                )
            if change == "zip_extra":
                archive.writestr("rule/extra", "hidden")
            if change == "zip_duplicate":
                with pytest.warns(UserWarning):
                    archive.writestr("rule/summary.md", "duplicate")
            if change == "zip_unsafe":
                archive.writestr("../escape", "bad")
        payload[zip_path] = b"not zip" if change == "zip_invalid" else buffer.getvalue()
        digest = hashlib.sha256(payload[zip_path]).hexdigest()
        meta["digest"] = digest
        entry["provenance"]["artifact_digest"] = digest
    payload[artifact_path] = json.dumps(meta).encode()
    payload[run_path] = json.dumps(workflow).encode()
    with pytest.raises(reports.ReportError):
        provenance.verify_github_artifacts(tmp_path, REFERENCE, [entry], getter=payload.__getitem__)


def semantic_fixture(make):
    from lead_cleaner.answerability_evaluation import checks

    text = "Transfer included"
    digest = hashlib.sha256(text.encode()).hexdigest()
    turn = {
        "turn_id": "T1",
        "answerability": "answerable",
        "evaluation_time": "2026-10-05T00:00:00+00:00",
        "business_date": "2026-10-05",
        "facets": [
            {
                "facet_id": "transfer",
                "required": True,
                "answerable": True,
                "support_groups": [["k1"]],
            }
        ],
        "expected_facts": [],
        "expected_state": None,
    }
    snapshot = {
        "chunks": [
            {
                "chunk": {"chunk_id": "k1", "text": text},
                "sha256": digest,
                "valid_from": None,
                "valid_to": None,
                "validity_basis": "evaluation_time",
            }
        ]
    }
    dataset = {
        "dataset_hash": "dataset",
        "knowledge_hash": "knowledge",
        "cases": [{"case_id": "AB01", "snapshot_id": "s1", "turns": [turn]}],
        "snapshots": {"s1": snapshot},
    }
    data = raw()
    observation = data["observations"][0]
    observation.update(
        reply_text=text,
        api_status=200,
        provided_context=[{"chunk_id": "k1", "text": text}],
        response={"reply_draft": {"source_ids": ["k1"]}},
    )
    data["assertions"] = checks.score_observation(turn, snapshot, observation)
    data["metadata"]["expected_keys"] = checks.expected_keys(dataset, "rule_only")
    run = make(data)
    semantic = {
        "observation_hash": reports.content_hash(observation),
        "rubric_version": checks.RUBRIC,
        "claims_complete": True,
        "completeness_rationale": "The full reply contains this single claim",
        "claims": [
            {
                "claim_id": "claim-1",
                "start": 0,
                "end": len(text),
                "text": text,
                "proposition": text,
                "rationale": "Same service is stated in the provided source",
                "facet_id": "transfer",
                "verdict": "supported",
                "review_status": "reviewed",
                "evidence_refs": [
                    {
                        "chunk_id": "k1",
                        "sha256": digest,
                        "start": 0,
                        "end": len(text),
                        "quote": text,
                    }
                ],
            }
        ],
        "answered_facets": ["transfer"],
        "action_appropriate": True,
        "gap_disclosed": True,
        "clarification_appropriate": True,
        "reply_action": "answer",
    }
    review = {"review_set_id": "semantic-1", "reviews": []}
    for row in run["assertions"]:
        if row["behavior_status"] != "needs_review":
            continue
        for role in ("developer", "sales"):
            review["reviews"].append(
                {
                    "review_id": row["assertion_id"] + "-" + role,
                    "key": list(reports.key(row)),
                    "run_manifest_hash": run["manifest_hash"],
                    "output_hash": row["observation_hash"],
                    "rubric_hash": "rubric",
                    "reviewer": role + "-person",
                    "role": role,
                    "reason": "Reviewed original source",
                    "reviewed_at": "2026-10-05T00:00:00Z",
                    "verdict": "pass",
                    "semantic": copy.deepcopy(semantic),
                }
            )
    context = trusted(run)
    context["accepted_review_set_hashes"] = [reports.content_hash(review)]
    return run, dataset, review, context


def test_semantic_reviews_recompute_actual_behavior_without_rewriting(make):
    run, dataset, review, context = semantic_fixture(make)
    before = Path(run["directory"], "assertions.jsonl").read_bytes()
    decision = check("behavior", run, dataset=dataset, review_set=review, trust_context=context)
    assert decision["exit_code"] == 0, decision["reasons"]
    assert all(
        r["behavior_status"] == "pass" for r in decision["effective_assertions"]["rule_only"]
    )
    assert Path(run["directory"], "assertions.jsonl").read_bytes() == before
    approval = authorize(run, context, review_set=review)
    accepted = gates.accept_baseline(
        run,
        previous=None,
        known_issues=[],
        approval=approval,
        trust_context=context,
        review_set=review,
        dataset=dataset,
    )
    assert accepted["review_set_hash"] == reports.content_hash(review)


@pytest.mark.parametrize(
    "change", ["no_dataset", "wrong_hash", "wrong_keys", "no_semantic", "wrong_span", "verdict"]
)
def test_semantic_identity_approval_does_not_replace_evidence_checks(make, change):
    run, dataset, review, context = semantic_fixture(make)
    if change == "no_dataset":
        dataset = None
    elif change == "wrong_hash":
        dataset["knowledge_hash"] = "another"
    elif change == "wrong_keys":
        dataset["cases"][0]["case_id"] = "AB02"
    elif change == "no_semantic":
        del review["reviews"][0]["semantic"]
    elif change == "wrong_span":
        for r in review["reviews"]:
            r["semantic"]["claims"][0]["start"] = 1
    else:
        for r in review["reviews"]:
            r["semantic"]["clarification_appropriate"] = False
    context["accepted_review_set_hashes"] = [reports.content_hash(review)]
    with pytest.raises(reports.ReportError):
        trust.effective_assertions(run, review, context, dataset=dataset)


def test_different_semantic_claim_inventory_stays_pending(make):
    run, dataset, review, context = semantic_fixture(make)
    review["reviews"][0]["semantic"]["completeness_rationale"] = "Different signed inventory"
    context["accepted_review_set_hashes"] = [reports.content_hash(review)]
    rows, _, _ = trust.effective_assertions(run, review, context, dataset=dataset)
    assert (
        next(r for r in rows if r["assertion_id"] == "answer_content")["behavior_status"]
        == "needs_review"
    )


def test_low_level_git_wrapper_uses_read_only_arguments(monkeypatch, tmp_path):
    calls = []

    def execute(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=" value ")

    monkeypatch.setattr(trust.subprocess, "run", execute)
    assert trust.git(tmp_path, "rev-parse", "HEAD") == "value"
    assert calls[0][0] == "git"


@pytest.mark.parametrize("change", ["duplicate", "resolved_no_commit", "wrong_protocol"])
def test_invalid_issue_lifecycle_cannot_enter_gate(make, change):
    run = make(status="fail")
    issues = [issue(run)]
    if change == "duplicate":
        issues.append(dict(issues[0]))
    elif change == "resolved_no_commit":
        issues[0]["status"] = "resolved"
    else:
        issues[0]["protocol_id"] = "p0-01.v1"
    assert check("inventory", run, known_issues=issues)["exit_code"] == 3


def test_missing_authoritative_keys_incomplete_baseline_and_unknown_comparison(make):
    run = make()
    assert (
        gates.evaluate_gate(
            "inventory",
            [run],
            candidate_sha=SHA,
            expected_keys_by_mode={},
            expected_retrieval_keys_by_mode={},
        )["exit_code"]
        == 3
    )
    baseline = make(status="needs_review")
    record = {"acceptance_id": "invalid-baseline", "run": baseline}
    assert (
        check(
            "regression",
            run,
            baselines={"rule_only": record},
            trust_context=trusted(run, previous=record),
        )["exit_code"]
        == 3
    )
    with pytest.raises(reports.ReportError):
        gates.compare_retrieval([], run["retrieval"])
    unknown = copy.deepcopy(run["retrieval"])
    unknown[0]["metrics"]["ndcg"].update(applicability="incomplete_judgments", value=None)
    with pytest.raises(reports.ReportError):
        gates.compare_retrieval(unknown, unknown)


def test_retrieval_mode_and_observation_stage_digest_enforced(make):
    data = raw("mocked_model")
    data["metadata"]["expected_retrieval_keys"] = [["AB01", "raw_query"]]
    with pytest.raises(reports.ReportError):
        make(data)
    run = make()
    path = Path(run["directory"])
    (path / "OBSERVATIONS").write_bytes(b"forged")
    manifest = reports.read_json(path / "manifest.json")
    manifest["files"]["OBSERVATIONS"] = {
        "sha256": reports.file_hash(path / "OBSERVATIONS"),
        "size": 6,
    }
    (path / "manifest.json").write_bytes(reports.canonical_json(manifest) + b"\n")
    (path / "COMPLETED").write_text(reports.file_hash(path / "manifest.json"), encoding="ascii")
    with pytest.raises(reports.ReportError, match="stage"):
        reports.load_run(path)


def test_atomic_issue_snapshots_preserve_failures_and_trusted_record(make):
    runs = [make(status="fail"), make(mode="mocked_model")]
    issues = [issue(runs[0])]
    context = trusted(runs[0], issues)
    context["verified_artifacts"].append(artifact(runs[1]))
    approvals = {
        r["metadata"]["mode"]: authorize(r, context, issues, identifier=r["metadata"]["mode"])
        for r in runs
    }
    bundle = gates.accept_baselines(
        runs, previous={}, known_issues=issues, approvals=approvals, trust_context=context
    )
    assert bundle["known_issues"] == issues
    assert context["latest_accepted_baselines"] == {}


def test_one_role_and_self_reported_trust_cannot_authorize(make):
    run = make(status="needs_review")
    review = reviews_for(run)
    context = trusted(run)
    context["accepted_review_set_hashes"] = [reports.content_hash(review)]
    run["metadata"]["review_required_roles"] = ["developer"]
    with pytest.raises(reports.ReportError):
        trust.effective_assertions(run, review, context)
    clean = make()
    with pytest.raises(reports.ReportError):
        provenance.require_verified_artifact(
            clean, {"trusted": True, "provenance": artifact(clean)}
        )
    candidate_context = {
        "trusted": True,
        "known_issues_hash": reports.content_hash([]),
        "latest_accepted_baselines": {"rule_only": "self"},
    }
    assert (
        check(
            "regression",
            clean,
            baselines={"rule_only": {"acceptance_id": "self", "run": clean}},
            trust_context=candidate_context,
        )["exit_code"]
        == 3
    )


def test_candidate_and_baseline_reviews_use_independent_approved_sets(make):
    initial, dataset, baseline_reviews, context = semantic_fixture(make)
    old = {"acceptance_id": "old-reviewed", "run": initial, "review_set": baseline_reviews}
    data = {
        name: copy.deepcopy(initial[name])
        for name in ("metadata", "observations", "assertions", "retrieval", "metrics")
    }
    data["metadata"]["run_id"] = "second-run"
    candidate = make(data)
    candidate_reviews = copy.deepcopy(baseline_reviews)
    candidate_reviews["review_set_id"] = "candidate-set"
    for record in candidate_reviews["reviews"]:
        record["run_manifest_hash"] = candidate["manifest_hash"]
        record["review_id"] += "-candidate"
    context = trusted(candidate, previous=old)
    context["accepted_review_set_hashes"] = [
        reports.content_hash(baseline_reviews),
        reports.content_hash(candidate_reviews),
    ]
    result = check(
        "regression",
        candidate,
        baselines={"rule_only": old},
        review_set=candidate_reviews,
        trust_context=context,
        dataset=dataset,
    )
    assert result["exit_code"] == 0, result["reasons"]
    wrong = dict(old, review_set=candidate_reviews)
    assert (
        check(
            "regression",
            candidate,
            baselines={"rule_only": wrong},
            review_set=candidate_reviews,
            trust_context=context,
            dataset=dataset,
        )["exit_code"]
        == 3
    )


@pytest.mark.parametrize("mode", ["rule_only", "mocked_model"])
def test_regression_reuses_real_api_equivalent_semantics_but_not_behavior_or_acceptance(
    tmp_path, mode
):
    from tests.test_answerability_review_reuse import semantic_case

    case = semantic_case(tmp_path, mode=mode)
    run = case["candidate"]
    options = {
        "candidate_sha": run["metadata"]["tested_commit"],
        "baselines": {mode: case["record"]},
        "known_issues": case["issues"],
        "trust_context": case["trust"],
        "dataset": case["dataset"],
    }
    raw_before = Path(run["directory"], "assertions.jsonl").read_bytes()
    decision = check("regression", run, **options)
    assert decision["exit_code"] == 0, decision["reasons"]
    assert len(decision["derived_adjudications"][mode]) == 3
    assert all(row["behavior_status"] == "pass" for row in decision["effective_assertions"][mode])
    assert Path(run["directory"], "assertions.jsonl").read_bytes() == raw_before
    assert check("behavior", run, **options)["exit_code"] == 1
    assert check("inventory", run, **options)["derived_adjudications"][mode] == []
    case["trust"]["verified_artifacts"] = [artifact(run)]
    with pytest.raises(reports.ReportError, match="Unknown or unreviewed"):
        gates.accept_baseline(
            run,
            previous=case["record"],
            known_issues=case["issues"],
            approval={},
            trust_context=case["trust"],
            dataset=case["dataset"],
        )


@pytest.mark.parametrize(
    "change", ["reply", "evidence", "empty_source_review", "current_disagreement"]
)
def test_regression_reuse_cannot_hide_changed_evidence_or_current_review_disagreement(
    tmp_path, change
):
    from tests.test_answerability_review_reuse import reseal, semantic_case

    case = semantic_case(tmp_path)
    if change == "reply":
        reseal(
            case,
            tmp_path / "changed",
            lambda data: data["observations"][0].update(reply_text="Definitely booked!"),
        )
    elif change == "evidence":
        reseal(
            case,
            tmp_path / "changed",
            lambda data: data["observations"][0]["provided_context"][0].update(
                text="Different evidence"
            ),
        )
    elif change == "empty_source_review":
        case["record"]["review_set"] = trust.EMPTY_REVIEW_SET
    review_set = None
    if change == "current_disagreement":
        review_set = copy.deepcopy(case["reviews"])
        review_set["review_set_id"] = "current-disagreement"
        for record in review_set["reviews"]:
            record["run_manifest_hash"] = case["candidate"]["manifest_hash"]
            record["output_hash"] = case["candidate"]["assertions"][0]["observation_hash"]
            record["verdict"] = "pass" if record["role"] == "developer" else "fail"
        case["trust"]["accepted_review_set_hashes"].append(reports.content_hash(review_set))
    run = case["candidate"]
    decision = check(
        "regression",
        run,
        candidate_sha=run["metadata"]["tested_commit"],
        baselines={"mocked_model": case["record"]},
        known_issues=case["issues"],
        trust_context=case["trust"],
        dataset=case["dataset"],
        review_set=review_set,
    )
    assert decision["exit_code"] in {1, 3}, decision
    assert decision["derived_adjudications"].get("mocked_model", []) == []


def test_reused_human_failure_needs_current_exact_open_issue(tmp_path):
    from tests.test_answerability_review_reuse import semantic_case

    case = semantic_case(tmp_path, verdict="fail")
    run = case["candidate"]
    kwargs = {
        "candidate_sha": run["metadata"]["tested_commit"],
        "baselines": {"mocked_model": case["record"]},
        "known_issues": case["issues"],
        "trust_context": case["trust"],
        "dataset": case["dataset"],
    }
    decision = check("regression", run, **kwargs)
    assert decision["exit_code"] == 0, decision["reasons"]
    rows = decision["effective_assertions"]["mocked_model"]
    assert (
        next(r for r in rows if r["assertion_id"] == "answer_content")["behavior_status"] == "fail"
    )
    case["trust"]["known_issues_hash"] = reports.content_hash([])
    kwargs["known_issues"] = []
    assert check("regression", run, **kwargs)["exit_code"] == 1


@pytest.mark.parametrize("change", ["keys", "provenance", "automatic"])
def test_gate_rejects_reuse_helper_overriding_immutable_boundaries(tmp_path, monkeypatch, change):
    from tests.test_answerability_review_reuse import semantic_case
    from lead_cleaner.answerability_evaluation import review_reuse

    case = semantic_case(tmp_path)

    def invalid_reuse(baseline, record, candidate, rows, context, dataset):
        changed = copy.deepcopy(rows)
        if change == "keys":
            changed.pop()
        elif change == "provenance":
            changed[2]["observation_hash"] = "different"
        else:
            changed[0]["details"] = {"overwritten_automatic": True}
        return changed, []

    monkeypatch.setattr(review_reuse, "reuse_reviewed_assertions", invalid_reuse)
    decision = check(
        "regression",
        case["candidate"],
        candidate_sha=case["candidate"]["metadata"]["tested_commit"],
        baselines={"mocked_model": case["record"]},
        known_issues=case["issues"],
        trust_context=case["trust"],
        dataset=case["dataset"],
    )
    assert decision["exit_code"] == 3


def test_known_automatic_fact_failure_is_preserved_while_semantic_review_is_reused(tmp_path):
    from tests.test_answerability_review_reuse import semantic_case

    case = semantic_case(tmp_path, auto_failure=True)
    run = case["candidate"]
    before = next(r for r in run["assertions"] if r["assertion_id"] == "facts_state")
    kwargs = {
        "candidate_sha": run["metadata"]["tested_commit"],
        "baselines": {"mocked_model": case["record"]},
        "known_issues": case["issues"],
        "trust_context": case["trust"],
        "dataset": case["dataset"],
    }
    decision = check("regression", run, **kwargs)
    assert decision["exit_code"] == 0, decision["reasons"]
    assert len(decision["derived_adjudications"]["mocked_model"]) == 3
    after = next(
        r
        for r in decision["effective_assertions"]["mocked_model"]
        if r["assertion_id"] == "facts_state"
    )
    assert before == after and after["behavior_status"] == "fail"
    for current in (
        [],
        [dict(i, status="resolved", resolved_commit="c" * 40) for i in case["issues"]],
    ):
        kwargs["known_issues"] = current
        case["trust"]["known_issues_hash"] = reports.content_hash(current)
        rejected = check("regression", run, **kwargs)
        assert rejected["exit_code"] == 1
        assert any("unapproved failure" in r["message"] for r in rejected["reasons"])
