"""CLI composition tests; business adapters and external CI calls are replaced locally."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from lead_cleaner.evaluation import quality_cli as cli
from lead_cleaner.evaluation.quality_runner import run_quality_suite as actual_run_quality_suite
from lead_cleaner.evaluation.quality_schema import expected_keys


CANDIDATE = "a" * 40
TRUSTED = "b" * 40


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def harness(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    protocol = {
        "protocol_id": "p0-01.v1",
        "profile": "p0-01-ai-assisted.v1",
        "modes": {
            "rule_only": {"trials": 1, "case_count": 10},
            "mocked_model": {"trials": 1, "case_count": 12},
            "live": {"trials": 3, "case_count": 10},
        },
        "required_modes": ["rule_only", "mocked_model", "live"],
        "live_max_requests": 60,
        "allowed_live_hosts": ["dashscope.aliyuncs.com"],
    }
    write_json(root / "config/quality_baseline.v1.json", protocol)
    write_json(root / "config/quality_known_issues.v1.json", {"issues": []})
    write_json(root / "data/recommendation_eval/golden_cases.json", {"cases": []})
    cases = []
    for index in range(22):
        modes = ["rule_only", "live"] if index < 10 else ["mocked_model"]
        cases.append(
            {
                "case_id": f"case-{index}",
                "family": "cli",
                "language": "en",
                "applicable_modes": modes,
                "adapter": "memory",
                "payload": {},
                "assertions": [{"assertion_id": "target", "check": "not_opted_out"}],
            }
        )
    state = {
        "root": root,
        "protocol": protocol,
        "cases": cases,
        "runner_calls": [],
        "sealed": [],
        "decisions": [],
        "gate_calls": [],
        "loaded": [],
        "trusted_calls": [],
        "artifact_calls": [],
        "row_changes": {},
        "metadata_changes": {},
        "gate_exit": 0,
    }
    monkeypatch.delenv("QUALITY_MODEL_NAME", raising=False)
    monkeypatch.delenv("QUALITY_MODEL_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_cases", lambda project_root: deepcopy(state["cases"]))

    def runner(mode, **kwargs):
        state["runner_calls"].append((mode, kwargs))
        selected = [case for case in kwargs["cases"] if mode in case["applicable_modes"]]
        return {
            "observations": [],
            "metadata": {
                "mode": mode,
                "scenario_count": len(selected),
                "real_model_calls": 0,
                "live_simulated": mode == "live",
                "partial_suite": False,
            }
            | state["metadata_changes"],
        }

    def assertions(cases, observations, *, mode, trials):
        rows = []
        for key in expected_keys(cases, mode, trials):
            row = dict(
                zip(("mode", "case_id", "probe_id", "checkpoint", "assertion_id", "trial_id"), key)
            )
            row.update(
                execution_status="completed",
                behavior_status="pass",
                mandatory=True,
                severity="major",
                manual_review=False,
                failure_type=None,
                known_issue_id=None,
                actual=True,
                expected=True,
                observation_hash=None,
            )
            row.update(state["row_changes"])
            rows.append(row)
        return rows

    def seal(out, raw, **kwargs):
        out.mkdir()
        state["sealed"].append((out, raw, kwargs))
        return {"manifest_hash": "sealed-hash"}

    def load(path):
        state["loaded"].append(Path(path))
        return {
            "directory": str(path),
            "manifest_hash": "baseline-hash",
            "metadata": {"tested_commit": CANDIDATE},
        }

    def trusted(root, ref, path):
        state["trusted_calls"].append((root, ref, path))
        return json.loads((root / path).read_text(encoding="utf-8"))

    def gate(kind, runs, **kwargs):
        state["gate_calls"].append((kind, runs, kwargs))
        return {
            "exit_code": state["gate_exit"],
            "gate_kind": kind,
            "suite_release_status": "blocked",
            "product_release_status": "not_evaluated",
        }

    def artifacts(root, ref, entries):
        state["artifact_calls"].append((root, ref, entries))
        return [entry["provenance"] for entry in entries]

    monkeypatch.setattr(cli, "run_quality_suite", runner)
    monkeypatch.setattr(cli, "evaluate_assertions", assertions)
    monkeypatch.setattr(
        cli,
        "build_metadata",
        lambda root, cases, mode, protocol: {
            "provisional": False,
            "mode": mode,
            "tested_commit": CANDIDATE,
        },
    )
    monkeypatch.setattr(cli, "seal_run", seal)
    monkeypatch.setattr(cli, "render_run_summary", lambda raw, cases: "frozen summary")
    monkeypatch.setattr(cli, "run_keyword_evaluation", lambda **kwargs: {"v4": "original"})
    monkeypatch.setattr(
        cli, "recommendation_contract_report", lambda payload: {"kind": "data_contract"}
    )
    monkeypatch.setattr(cli, "load_run", load)
    monkeypatch.setattr(cli, "evaluate_gate", gate)
    monkeypatch.setattr(
        cli, "write_decision", lambda out, decision: state["decisions"].append((out, decision))
    )
    monkeypatch.setattr(
        cli, "load_trust_context", lambda root, ref: {"repository": "example/project"}
    )
    monkeypatch.setattr(cli, "verify_protected_files", lambda root, ref: {"trusted_ref": ref})
    monkeypatch.setattr(cli, "trusted_json", trusted)
    monkeypatch.setattr(cli, "verify_github_artifacts", artifacts)
    return state


def invoke(state, *args):
    return cli.main(["--project-root", str(state["root"]), *map(str, args)])


def run_args(state, mode="rule_only", *extra):
    return ["run", "--mode", mode, "--out", state["root"] / "run", *extra]


def check_args(state, gate="inventory", *extra):
    return ["check", "--gate", gate, "--candidate-sha", CANDIDATE, *extra]


@pytest.mark.parametrize("mode", ["rule_only", "mocked_model"])
def test_run_preserves_subreport_scope_and_nonapproval_output(harness, capsys, mode):
    assert invoke(harness, *run_args(harness, mode)) == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["provisional"] is False
    assert stdout["real_model_calls"] == 0
    assert stdout["scenario_count"] == (10 if mode == "rule_only" else 12)
    _, raw, kwargs = harness["sealed"][0]
    assert raw["summary"] == "frozen summary"
    assert raw["metadata"]["expected_keys"] == kwargs["expected_keys"]
    assert set(raw["subreports"]) == (
        {"retrieval-v4", "recommendation-contract"} if mode == "rule_only" else set()
    )


@pytest.mark.parametrize("metadata_change", [{"partial_suite": True}, {"live_simulated": True}])
def test_simulated_or_partial_run_is_forced_provisional(harness, capsys, metadata_change):
    harness["metadata_changes"] = metadata_change
    assert invoke(harness, *run_args(harness)) == 0
    assert json.loads(capsys.readouterr().out)["provisional"] is True


def test_business_failure_is_recorded_without_claiming_execution_error(harness, capsys):
    harness["row_changes"] = {"behavior_status": "fail", "failure_type": "business_mismatch"}
    assert invoke(harness, *run_args(harness)) == 0
    assert json.loads(capsys.readouterr().out)["business_failures"] == 10


def test_execution_failure_and_pending_reviews_remain_distinct(harness, capsys):
    harness["row_changes"] = {"execution_status": "error", "behavior_status": None}
    assert invoke(harness, *run_args(harness)) == 2
    assert harness["sealed"]
    harness["row_changes"] = {
        "execution_status": "completed",
        "behavior_status": "needs_review",
        "manual_review": True,
    }
    args = run_args(harness)
    args[4] = harness["root"] / "review-run"
    assert invoke(harness, *args) == 0
    output = capsys.readouterr().out.splitlines()
    assert json.loads(output[-1])["needs_review"] == 10


@pytest.mark.parametrize(
    "extra,error",
    [
        (["--max-requests", "0"], "request budget"),
        (["--max-requests", "61"], "request budget"),
    ],
)
def test_invalid_budget_is_rejected_before_runner(harness, capsys, extra, error):
    assert invoke(harness, *run_args(harness, "rule_only", *extra)) == 2
    assert error in capsys.readouterr().err
    assert harness["runner_calls"] == []


def test_output_directory_is_never_reused(harness, capsys):
    (harness["root"] / "run").mkdir()
    assert invoke(harness, *run_args(harness)) == 2
    assert "already exists" in capsys.readouterr().err
    assert harness["runner_calls"] == []


@pytest.mark.parametrize(
    "extra,error",
    [
        ([], "allow-network"),
        (["--allow-network"], "explicit model"),
        (
            ["--allow-network", "--model", "chosen", "--base-url", "https://other.example/v1"],
            "allowlist",
        ),
    ],
)
def test_live_requires_explicit_authorization_model_and_allowed_host(harness, capsys, extra, error):
    assert invoke(harness, *run_args(harness, "live", *extra)) == 2
    assert error in capsys.readouterr().err
    assert not harness["runner_calls"]


def test_live_explicit_configuration_and_environment_model_are_forwarded(
    harness, monkeypatch, capsys
):
    monkeypatch.setenv("QUALITY_MODEL_NAME", "environment-model")
    monkeypatch.setenv("TEST_QUALITY_SECRET", "private-key")
    assert (
        invoke(
            harness,
            *run_args(
                harness,
                "live",
                "--allow-network",
                "--api-key-env",
                "TEST_QUALITY_SECRET",
                "--timeout",
                "12",
                "--max-requests",
                "48",
            ),
        )
        == 0
    )
    mode, call = harness["runner_calls"][0]
    assert mode == "live"
    assert call["trials"] == 3
    assert call["max_requests"] == 48
    assert call["live_config"] == {
        "api_key": "private-key",
        "model": "environment-model",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "timeout": 12.0,
    }
    output = capsys.readouterr()
    assert "private-key" not in output.out + output.err
    assert json.loads(output.out)["provisional"] is True


@pytest.mark.parametrize("timeout", ["0", "61"])
def test_actual_live_runner_rejects_invalid_timeout_without_network(
    harness, monkeypatch, capsys, timeout
):
    monkeypatch.setattr(cli, "run_quality_suite", actual_run_quality_suite)
    monkeypatch.setenv("QUALITY_MODEL_API_KEY", "test-only-no-call")
    assert (
        invoke(
            harness,
            *run_args(
                harness,
                "live",
                "--allow-network",
                "--model",
                "chosen",
                "--timeout",
                timeout,
            ),
        )
        == 2
    )
    assert "timeout" in capsys.readouterr().err
    assert not harness["sealed"]


def test_actual_live_runner_requires_credentials_and_never_falls_back(harness, monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_quality_suite", actual_run_quality_suite)
    assert invoke(harness, *run_args(harness, "live", "--allow-network", "--model", "chosen")) == 2
    assert "credential" in capsys.readouterr().err.lower()
    assert not harness["sealed"]


@pytest.mark.parametrize("mutation", ["protocol", "profile", "modes"])
def test_protocol_must_match_frozen_identity_and_matrix(harness, capsys, mutation):
    protocol = deepcopy(harness["protocol"])
    if mutation == "modes":
        protocol["modes"]["live"]["trials"] = 1
    else:
        protocol["protocol_id" if mutation == "protocol" else "profile"] = "unapproved"
    path = harness["root"] / "custom.json"
    write_json(path, protocol)
    assert invoke(harness, *run_args(harness, "rule_only", "--protocol", path)) == 2
    assert capsys.readouterr().err
    assert not harness["runner_calls"]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "schema"])
def test_case_contract_rejects_missing_duplicate_or_invalid_cases(harness, mutation):
    if mutation == "missing":
        harness["cases"].pop()
    elif mutation == "duplicate":
        harness["cases"][1]["case_id"] = harness["cases"][0]["case_id"]
    else:
        harness["cases"][0]["unexpected"] = True
    assert invoke(harness, *run_args(harness)) == 2
    assert not harness["runner_calls"]


def test_known_issue_matching_is_exact_open_and_unambiguous():
    row = {
        "mode": "mocked_model",
        "case_id": "F01",
        "probe_id": "main",
        "checkpoint": "result",
        "assertion_id": "target",
        "failure_type": "unsafe_fact_accepted",
        "severity": "major",
        "behavior_status": "fail",
        "known_issue_id": None,
    }
    issue = {
        key: value for key, value in row.items() if key not in {"behavior_status", "known_issue_id"}
    }
    issue.update(status="open", issue_id="issue")
    cli._match_issues([row], [issue | {"status": "resolved"}, issue | {"severity": "minor"}])
    assert row["known_issue_id"] is None
    cli._match_issues([row], [issue])
    assert row["known_issue_id"] == "issue"
    with pytest.raises(ValueError, match="ambiguous"):
        cli._match_issues([row], [issue, issue | {"issue_id": "other"}])
    passed = row | {"behavior_status": "pass", "known_issue_id": None}
    cli._match_issues([passed], [issue])
    assert passed["known_issue_id"] is None


@pytest.mark.parametrize("gate", ["regression", "release"])
def test_noninventory_gate_requires_trusted_ref(harness, capsys, gate):
    assert invoke(harness, *check_args(harness, gate)) == 3
    assert "trusted-ref" in capsys.readouterr().err
    assert not harness["gate_calls"]


def test_inventory_forwards_candidate_without_implicitly_running_models(harness, capsys):
    run_path = harness["root"] / "existing-run"
    harness["gate_exit"] = 1
    assert invoke(harness, *check_args(harness, "inventory", "--run", run_path)) == 1
    kind, runs, kwargs = harness["gate_calls"][0]
    assert (kind, kwargs["candidate_sha"]) == ("inventory", CANDIDATE)
    assert kwargs["required_modes"] is None
    assert kwargs["review_set"] is None
    assert harness["loaded"] == [run_path]
    assert not harness["runner_calls"]
    assert json.loads(capsys.readouterr().out)["suite_release_status"] == "blocked"
    assert harness["decisions"][0][0].parent == harness["root"] / "data/runtime/quality-decisions"


def test_release_uses_verified_provenance_review_set_and_trusted_baseline(harness):
    report_index = harness["root"] / "report-index.json"
    entries = [
        {"directory": str(harness["root"] / "rule"), "provenance": {"tested_commit": CANDIDATE}},
    ]
    write_json(report_index, {"reports": entries})
    baseline_index = harness["root"] / "baseline-index.json"
    write_json(
        baseline_index,
        {
            "accepted": {
                "rule_only": {
                    "directory": "baselines/rule",
                    "manifest_hash": "baseline-hash",
                    "acceptance_id": "accepted-1",
                },
            }
        },
    )
    review = harness["root"] / "reviews.json"
    write_json(review, {"review_set_id": "approved-reviews"})
    out = harness["root"] / "decision"
    assert (
        invoke(
            harness,
            *check_args(
                harness,
                "release",
                "--trusted-ref",
                TRUSTED,
                "--report-index",
                report_index,
                "--baseline-index",
                baseline_index,
                "--review-set",
                review,
                "--out",
                out,
            ),
        )
        == 0
    )
    _, _, kwargs = harness["gate_calls"][0]
    assert kwargs["required_modes"] == ["rule_only", "mocked_model", "live"]
    assert kwargs["provenance"] == [entries[0]["provenance"]]
    assert kwargs["trust_context"]["verified_artifacts"] == [entries[0]["provenance"]]
    assert kwargs["review_set"] == {"review_set_id": "approved-reviews"}
    assert kwargs["baselines"]["rule_only"]["acceptance_id"] == "accepted-1"
    assert harness["artifact_calls"] == [(harness["root"], TRUSTED, entries)]
    assert harness["decisions"][0][0] == out
    assert not harness["runner_calls"]


def test_report_index_without_provenance_is_not_fabricated(harness):
    index = harness["root"] / "index.json"
    write_json(index, {"reports": [{"directory": str(harness["root"] / "run")}]})
    assert invoke(harness, *check_args(harness, "inventory", "--report-index", index)) == 0
    assert harness["gate_calls"][0][2]["provenance"] == []
    assert not harness["artifact_calls"]


def test_unknown_release_profile_is_rejected_before_loading_runs(harness, capsys):
    assert (
        invoke(
            harness,
            *check_args(
                harness,
                "release",
                "--trusted-ref",
                TRUSTED,
                "--profile",
                "unapproved",
            ),
        )
        == 3
    )
    assert "release profile" in capsys.readouterr().err
    assert not harness["loaded"]


def test_untrusted_local_baseline_is_only_read_as_data_for_inventory(harness):
    path = harness["root"] / "baseline-index.json"
    write_json(
        path,
        {
            "accepted": {
                "rule_only": {
                    "directory": "baselines/rule",
                    "manifest_hash": "baseline-hash",
                    "acceptance_id": "accepted-1",
                },
            }
        },
    )
    baselines = cli._load_baselines(harness["root"], path, None)
    assert baselines["rule_only"]["acceptance_id"] == "accepted-1"
    assert not harness["trusted_calls"]


@pytest.mark.parametrize("problem", ["escape", "hash"])
def test_baseline_path_and_manifest_must_match_accepted_index(harness, problem):
    path = harness["root"] / "baseline-index.json"
    write_json(
        path,
        {
            "accepted": {
                "rule_only": {
                    "directory": "../outside" if problem == "escape" else "baselines/rule",
                    "manifest_hash": "wrong-hash" if problem == "hash" else "baseline-hash",
                    "acceptance_id": "accepted-1",
                },
            }
        },
    )
    with pytest.raises(ValueError, match="escaped" if problem == "escape" else "hash mismatch"):
        cli._load_baselines(harness["root"], path, TRUSTED)


@pytest.mark.parametrize(
    "dependency", ["load_run", "verify_protected_files", "verify_github_artifacts"]
)
def test_evidence_failures_propagate_without_creating_a_decision(
    harness, monkeypatch, capsys, dependency
):
    def fail(*args, **kwargs):
        raise ValueError("evidence mismatch")

    monkeypatch.setattr(cli, dependency, fail)
    index = harness["root"] / "index.json"
    write_json(
        index,
        {
            "reports": [
                {
                    "directory": str(harness["root"] / "run"),
                    "provenance": {"tested_commit": CANDIDATE},
                },
            ]
        },
    )
    assert (
        invoke(
            harness,
            *check_args(
                harness,
                "release",
                "--trusted-ref",
                TRUSTED,
                "--report-index",
                index,
            ),
        )
        == 3
    )
    assert "evidence mismatch" in capsys.readouterr().err
    assert not harness["decisions"]


def test_verify_policy_verifies_remote_anchor_then_protected_files(harness, capsys):
    assert invoke(harness, "verify-policy", "--trusted-ref", TRUSTED) == 0
    assert json.loads(capsys.readouterr().out) == {"trusted_ref": TRUSTED}


@pytest.mark.parametrize(
    "exception", [OSError("missing"), KeyError("key"), subprocess.CalledProcessError(1, ["git"])]
)
def test_cli_formats_expected_io_and_git_errors(harness, monkeypatch, capsys, exception):
    def fail(*args, **kwargs):
        raise exception

    monkeypatch.setattr(cli, "load_trust_context", fail)
    assert invoke(harness, "verify-policy", "--trusted-ref", TRUSTED) == 3
    output = json.loads(capsys.readouterr().err)
    assert output["exit_code"] == 3
    assert output["error_type"] == type(exception).__name__


@pytest.mark.parametrize(
    "args",
    [[], ["run"], ["run", "--mode", "wrong", "--out", "unused"], ["check", "--gate", "inventory"]],
)
def test_parser_rejects_incomplete_or_unknown_arguments(args):
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2


def dependency_module():
    path = Path(__file__).resolve().parents[1] / "scripts/check_quality_dependencies.py"
    spec = importlib.util.spec_from_file_location("quality_dependency_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dependency_check_matches_actual_lock_offline():
    module = dependency_module()
    assert module.check_requirements(Path(__file__).resolve().parents[1])


def test_dependency_drift_is_detected_without_changing_the_real_lock(tmp_path, monkeypatch):
    module = dependency_module()
    (tmp_path / "requirements.txt").write_text("# frozen\npackage==1\n", encoding="utf-8")
    calls = []

    def export(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="# exported\npackage==2\n")

    monkeypatch.setattr(module.subprocess, "run", export)
    assert module.check_requirements(tmp_path) is False
    assert calls[0][0][0:3] == ["uv", "export", "--locked"]
    assert "--offline" in calls[0][0]
    assert calls[0][1]["cwd"] == tmp_path
    assert module.normalized_requirements(" # comment\n b==2 \na==1\n") == ["a==1", "b==2"]


def test_release_without_report_index_does_not_fetch_or_run_models(harness):
    harness["gate_exit"] = 2
    assert invoke(harness, *check_args(harness, "release", "--trusted-ref", TRUSTED)) == 2
    assert harness["gate_calls"][0][1] == []
    assert not harness["artifact_calls"]
    assert not harness["runner_calls"]


def journal_events(harness):
    path = harness["root"] / "run.diagnostics/events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_successful_run_keeps_diagnostics_separate_from_sealed_report(harness):
    assert invoke(harness, *run_args(harness)) == 0
    assert harness["sealed"][0][1]["metadata"]["review_required_roles"] == ["developer", "sales"]
    events = journal_events(harness)
    assert [event["event"] for event in events] == ["started", "fingerprints", "sealed"]
    assert events[-1]["exit_code"] == 0
    assert harness["runner_calls"][0][1]["journal_path"] == (
        harness["root"] / "run.diagnostics/events.jsonl"
    )


def test_keyboard_interrupt_retains_evidence_and_returns_execution_error(
    harness, monkeypatch, capsys
):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli, "run_quality_suite", interrupt)
    assert invoke(harness, *run_args(harness)) == 2
    events = journal_events(harness)
    assert [event["event"] for event in events] == ["started", "fingerprints", "interrupted"]
    assert events[-1]["error_type"] == "KeyboardInterrupt"
    assert not harness["sealed"]
    assert json.loads(capsys.readouterr().err)["exit_code"] == 2


@pytest.mark.parametrize(
    "field",
    [
        "code_hash",
        "evaluator_hash",
        "suite_hash",
        "knowledge_hash",
        "evaluation_data_hash",
        "environment_hash",
    ],
)
def test_changes_during_evaluation_prevent_sealing_but_keep_diagnostics(
    harness, monkeypatch, capsys, field
):
    snapshots = iter(
        [
            {
                "provisional": False,
                "mode": "rule_only",
                "tested_commit": CANDIDATE,
                field: "before",
            },
            {"provisional": False, "mode": "rule_only", "tested_commit": CANDIDATE, field: "after"},
        ]
    )
    monkeypatch.setattr(cli, "build_metadata", lambda *args: next(snapshots))
    assert invoke(harness, *run_args(harness)) == 2
    assert "changed during execution" in capsys.readouterr().err
    assert not harness["sealed"]
    events = journal_events(harness)
    assert events[-1]["event"] == "error"
    assert events[-1]["error_type"] == "ValueError"
    assert events[-1]["recorded_at"]


def test_previous_diagnostics_are_not_overwritten(harness, capsys):
    directory = harness["root"] / "run.diagnostics"
    directory.mkdir()
    marker = directory / "old-evidence"
    marker.write_text("preserve", encoding="utf-8")
    assert invoke(harness, *run_args(harness)) == 2
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert not harness["runner_calls"]
    assert json.loads(capsys.readouterr().err)["error_type"] == "FileExistsError"


def test_output_recheck_catches_directory_created_after_diagnostics(harness):
    out = harness["root"] / "run"
    out.mkdir()
    args = cli._parser().parse_args(
        ["--project-root", str(harness["root"]), "run", "--mode", "rule_only", "--out", str(out)]
    )
    with pytest.raises(ValueError, match="already exists"):
        cli._execute_run(args, harness["root"] / "journal.jsonl")


@pytest.mark.parametrize("trusted", [False, True])
@pytest.mark.parametrize("review_source", ["inline", "file"])
@pytest.mark.parametrize("initial_source", ["index", "nested"])
def test_baselines_retain_initial_reference_and_frozen_reviews(
    harness, trusted, review_source, initial_source
):
    initial = {
        "directory": "baselines/initial",
        "manifest_hash": "baseline-hash",
        "acceptance_id": "initial-1",
    }
    accepted = {
        "directory": "baselines/current",
        "manifest_hash": "baseline-hash",
        "acceptance_id": "accepted-2",
    }
    review = {"review_set_id": "frozen-review"}
    if review_source == "inline":
        accepted["review_set"] = review
    else:
        accepted["review_set_path"] = "reviews/accepted.json"
        write_json(harness["root"] / "reviews/accepted.json", review)
    index = {"accepted": {"rule_only": accepted}}
    if initial_source == "index":
        index["initial"] = {"rule_only": initial}
    else:
        accepted["initial_baseline"] = initial
    path = harness["root"] / "baseline-index.json"
    write_json(path, index)
    result = cli._load_baselines(harness["root"], path, TRUSTED if trusted else None)
    assert result["rule_only"]["review_set"] == review
    assert result["rule_only"]["initial_baseline"]["acceptance_id"] == "initial-1"


def test_baseline_review_file_cannot_escape_project(harness):
    path = harness["root"] / "baseline-index.json"
    write_json(
        path,
        {
            "accepted": {
                "rule_only": {
                    "directory": "baselines/current",
                    "manifest_hash": "baseline-hash",
                    "acceptance_id": "accepted-2",
                    "review_set_path": "../outside.json",
                }
            }
        },
    )
    with pytest.raises(ValueError, match="review set escaped"):
        cli._load_baselines(harness["root"], path, TRUSTED)
