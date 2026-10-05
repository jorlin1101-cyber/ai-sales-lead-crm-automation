"""The bridge must compare individual outcomes and never conceal incomplete evidence."""

import copy
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "answerability_compatibility", ROOT / "scripts/check_answerability_compatibility.py"
)
assert SPEC and SPEC.loader
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


@pytest.fixture(scope="module")
def accepted():
    return bridge._baselines(ROOT)[0]


@pytest.fixture
def retrieval(accepted):
    return copy.deepcopy(accepted["rule_only"]["subreports"]["retrieval-v4"])


def test_frozen_manifest_requires_all_55_files(tmp_path):
    manifest = tmp_path / "freeze.json"
    frozen = {}
    for number in range(55):
        file = tmp_path / f"frozen-{number}.txt"
        file.write_text(str(number))
        frozen[file.name] = bridge._sha(file)
    manifest.write_text(json.dumps(frozen))
    result = bridge.audit_frozen_files(tmp_path, manifest)
    assert result["file_count"] == 55 and result["all_equal"]
    del frozen["frozen-0.txt"]
    manifest.write_text(json.dumps(frozen))
    with pytest.raises(bridge.CompatibilityError, match="55 files"):
        bridge.audit_frozen_files(tmp_path, manifest)


def test_frozen_bytes_missing_changed_and_no_line_normalization(tmp_path):
    item, manifest = tmp_path / "data.txt", tmp_path / "freeze.json"
    item.write_bytes(b"a\nb\n")
    manifest.write_text(json.dumps({"data.txt": hashlib.sha256(item.read_bytes()).hexdigest()}))
    assert bridge.audit_frozen_files(tmp_path, manifest, expected_count=1)["all_equal"]
    item.write_bytes(b"a\r\nb\r\n")
    assert not bridge.audit_frozen_files(tmp_path, manifest, expected_count=1)["all_equal"]
    item.unlink()
    result = bridge.audit_frozen_files(tmp_path, manifest, expected_count=1)
    assert result["files"][0]["actual"] is None
    with pytest.raises(bridge.CompatibilityError, match="55 files"):
        bridge.audit_frozen_files(tmp_path, manifest)


@pytest.mark.parametrize("name", ["../outside", "/outside", "C:/outside", "x\\y", "./x", "x//y"])
def test_reject_unsafe_frozen_paths(tmp_path, name):
    manifest = tmp_path / "freeze.json"
    manifest.write_text(json.dumps({name: "0" * 64}))
    with pytest.raises(bridge.CompatibilityError):
        bridge.audit_frozen_files(tmp_path, manifest, expected_count=1)


@pytest.mark.parametrize("value", [[], {"x": "bad"}, {"x": "g" * 64}])
def test_invalid_manifest_rejected(tmp_path, value):
    manifest = tmp_path / "freeze.json"
    manifest.write_text(json.dumps(value))
    with pytest.raises(bridge.CompatibilityError):
        bridge.audit_frozen_files(tmp_path, manifest, expected_count=1)


def test_retrieval_ignores_only_question_timing_and_order(retrieval):
    candidate = copy.deepcopy(retrieval)
    candidate["generated_at_utc"] = "later"
    candidate["indexing"]["index_build_ms"] = 99999
    for evaluation in candidate["evaluations"].values():
        evaluation["cases"].reverse()
        evaluation["latency"] = {"different_timing": True}
        for case in evaluation["cases"]:
            case["query_latency_ms"] += 1
    result = bridge.compare_retrieval(retrieval, candidate)
    assert result["all_equal"]
    assert result["question_path_count"] == 54


@pytest.mark.parametrize("mutation", ["case", "rank", "metric", "query", "contract"])
def test_retrieval_detects_case_and_aggregate_changes(retrieval, mutation):
    candidate = copy.deepcopy(retrieval)
    path = candidate["evaluations"]["runtime_rule_query"]
    case = path["cases"][0]
    if mutation == "case":
        case["ndcg_at_3"] += 0.000001
    elif mutation == "rank":
        case["retrieved_sources"][0]["relevance_grade"] = 0
    elif mutation == "metric":
        path["metrics"]["direct"]["top_1_hits"] += 1
    elif mutation == "query":
        case["input_query"] += " altered"
    else:
        candidate["retrieval"]["top_k"] = 999
    assert not bridge.compare_retrieval(retrieval, candidate)["all_equal"]


@pytest.mark.parametrize(
    "mutation", ["missing_path", "wrong_version", "missing_case", "duplicate_case"]
)
def test_incomplete_retrieval_rejected(retrieval, mutation):
    candidate = copy.deepcopy(retrieval)
    if mutation == "missing_path":
        del candidate["evaluations"]["raw_query"]
    elif mutation == "wrong_version":
        candidate["report_schema_version"] = "rag-eval-v5"
    elif mutation == "missing_case":
        candidate["evaluations"]["raw_query"]["cases"].pop()
    else:
        rows = candidate["evaluations"]["raw_query"]["cases"]
        rows[0] = rows[1]
    with pytest.raises(bridge.CompatibilityError):
        bridge.compare_retrieval(retrieval, candidate)


@pytest.mark.parametrize("field", bridge.OUTCOME_FIELDS)
def test_every_assertion_outcome_field_is_compared(accepted, field):
    before = accepted["mocked_model"]["assertions"]
    candidate = copy.deepcopy(before)
    candidate[0][field] = "changed"
    result = bridge.compare_assertions(before, candidate)
    assert not result["all_equal"]
    assert sum(not row["equal"] for row in result["rows"]) == 1


def test_assertion_identity_exact_and_volatile_payload_ignored(accepted):
    before = accepted["rule_only"]["assertions"]
    candidate = copy.deepcopy(before)
    candidate.reverse()
    candidate[0]["actual"] = {"random_id": "new-run"}
    candidate[0]["observation_hash"] = "another-run"
    assert bridge.compare_assertions(before, candidate)["all_equal"]
    candidate[0]["trial_id"] = "2"
    assert not bridge.compare_assertions(before, candidate)["all_equal"]
    candidate.append(copy.deepcopy(candidate[0]))
    with pytest.raises(bridge.CompatibilityError, match="Duplicate"):
        bridge.compare_assertions(before, candidate)


def test_run_separates_scores_frozen_fingerprints_and_new_context(accepted):
    before = accepted["rule_only"]
    candidate = copy.deepcopy(before)
    candidate["metadata"].update(
        code_hash="new-source", environment_hash="windows", provisional=True, source_dirty=True
    )
    result = bridge.compare_run(before, candidate, "rule_only")
    assert result["scores_equal"] and result["contract_fingerprints_equal"]
    assert not result["non_invariant_context"]["environment_hash"]["equal"]
    candidate["metadata"]["evaluator_hash"] = "different-byte-fingerprint"
    result = bridge.compare_run(before, candidate, "rule_only")
    assert result["scores_equal"] and result["contract_fingerprints_equal"]
    assert not result["baseline_raw_fingerprints"]["evaluator_hash"]["equal"]
    candidate["metadata"]["suite_hash"] = "changed-suite"
    result = bridge.compare_run(before, candidate, "rule_only")
    assert result["scores_equal"] and not result["contract_fingerprints_equal"]


@pytest.mark.parametrize("mutation", ["partial", "count", "live", "subreport", "recommendation"])
def test_run_requires_complete_legacy_contract(accepted, mutation):
    before = accepted["rule_only"]
    candidate = copy.deepcopy(before)
    if mutation == "partial":
        candidate["metadata"]["partial_suite"] = True
    elif mutation == "count":
        candidate["metadata"]["scenario_count"] = 9
    elif mutation == "live":
        candidate["metadata"]["real_model_calls"] = 1
    elif mutation == "subreport":
        del candidate["subreports"]["retrieval-v4"]
    else:
        candidate["subreports"]["recommendation-contract"]["case_count"] = 11
    with pytest.raises(bridge.CompatibilityError):
        bridge.compare_run(before, candidate, "rule_only")


def test_recommendation_compares_entire_contract(accepted):
    before = accepted["rule_only"]
    candidate = copy.deepcopy(before)
    candidate["subreports"]["recommendation-contract"]["checks"][0]["actual"] = "changed"
    assert not bridge.compare_run(before, candidate, "rule_only")["scores_equal"]


@pytest.fixture
def bridge_workspace(tmp_path, monkeypatch, accepted):
    root = tmp_path / "project"
    root.mkdir()
    files = {}
    for number in range(55):
        file = root / f"frozen-{number}.txt"
        file.write_text(str(number))
        files[file.name] = bridge._sha(file)
    folder = root / "data/runtime/p002-development"
    folder.mkdir(parents=True)
    (folder / "p001-frozen-files.json").write_text(json.dumps(files))
    monkeypatch.setattr(bridge, "_baselines", lambda root: (accepted, {"fixture": True}))
    calls = []

    def run_cli(project, out, mode):
        calls.append(mode)
        return {"exit_code": 0}

    monkeypatch.setattr(bridge, "_run_cli", run_cli)
    monkeypatch.setattr(bridge, "load_run", lambda path: copy.deepcopy(accepted[path.name]))
    return root, tmp_path / "new-evidence", calls


def test_bridge_runs_both_modes_preserves_reports_and_never_claims_formal(bridge_workspace):
    root, out, calls = bridge_workspace
    result = bridge.run_bridge(root, out)
    assert calls == ["rule_only", "mocked_model"]
    assert result["status"] == "pass" and result["exit_code"] == 0
    assert result["scenario_count"] == 22 and result["assertion_count"] == 29
    assert result["frozen_sources_unchanged"] and result["scores_equal"]
    assert result["formal_regression"] is False
    assert result["baseline_acceptance_performed"] is False
    assert json.loads((out / "compatibility-bridge.json").read_text()) == result
    with pytest.raises(FileExistsError):
        bridge.run_bridge(root, out)


def test_bridge_records_execution_failure_without_success(bridge_workspace, monkeypatch):
    root, out, _ = bridge_workspace
    monkeypatch.setattr(
        bridge, "_run_cli", lambda *a: (_ for _ in ()).throw(RuntimeError("failed"))
    )
    result = bridge.run_bridge(root, out)
    assert result["status"] == "error" and result["exit_code"] == 2
    assert result["error"]["type"] == "RuntimeError"
    assert (out / "compatibility-bridge.json").is_file()


def test_bridge_rechecks_all_frozen_bytes_after_execution(bridge_workspace, monkeypatch):
    root, out, _ = bridge_workspace

    def run_cli(*args):
        (root / "frozen-0.txt").write_text("changed during execution")
        return {"exit_code": 0}

    monkeypatch.setattr(bridge, "_run_cli", run_cli)
    result = bridge.run_bridge(root, out)
    assert result["status"] == "fail" and result["exit_code"] == 2
    assert not result["frozen_sources_unchanged"]
    assert result["scores_equal"]


def test_bridge_stops_on_changed_frozen_inputs(bridge_workspace):
    root, out, calls = bridge_workspace
    (root / "frozen-0.txt").write_text("already changed")
    result = bridge.run_bridge(root, out)
    assert result["status"] == "error" and calls == []


@pytest.mark.parametrize("returncode", [0, 7])
def test_original_cli_invocation_uses_real_entrypoint_and_captures_failure(
    tmp_path, monkeypatch, returncode
):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        kwargs["stdout"].write("original CLI output\n")
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(bridge.subprocess, "run", run)
    if returncode:
        with pytest.raises(bridge.CompatibilityError):
            bridge._run_cli(ROOT, tmp_path, "rule_only")
    else:
        assert bridge._run_cli(ROOT, tmp_path, "rule_only")["exit_code"] == 0
    command, kwargs = calls[0]
    assert command[4] == str(ROOT / "scripts/run_quality_eval.py")
    assert command[5:8] == ["--project-root", str(ROOT), "run"]
    assert "--allow-network" not in command
    assert kwargs["cwd"] == ROOT and kwargs["stderr"] == subprocess.STDOUT
    assert kwargs["env"]["PYTHONUTF8"] == "1"
    assert (tmp_path / "rule_only.log").read_text() == "original CLI output\n"
    assert (
        json.loads((tmp_path / "rule_only-invocation.json").read_text())["exit_code"] == returncode
    )


def test_main_reports_existing_output_without_overwrite(tmp_path):
    assert bridge.main(["--project-root", str(ROOT), "--out", str(tmp_path)]) == 2


def test_retrieval_keeps_raw_input_fingerprints_separate_from_scores(retrieval):
    candidate = copy.deepcopy(retrieval)
    candidate["dataset"]["sha256"] = "windows-checkout"
    candidate["knowledge_snapshot"]["sha256"] = "windows-checkout"
    result = bridge.compare_retrieval(retrieval, candidate)
    assert result["all_equal"]
    assert not result["input_byte_fingerprints_not_scores"]["dataset"]["equal"]
