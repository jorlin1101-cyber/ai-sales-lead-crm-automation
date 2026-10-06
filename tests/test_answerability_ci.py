"""Offline tests for trusted-policy enforcement, CI gates and upload binding."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "config/quality_answerability.v2.json"
INDEX = "config/quality_answerability_baseline_index.v2.json"
TRUST = "config/quality_answerability_trust.v2.json"


def script(name):
    spec = importlib.util.spec_from_file_location(
        "answerability_test_" + name, ROOT / "scripts" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(root):
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Answerability Test",
        "-c",
        "user.email=eval@example.test",
        "commit",
        "--quiet",
        "-m",
        "test accepted policy",
    )
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path):
    count = 0

    def create(*, protocol=True, index=True, accepted=None, trust=True):
        nonlocal count
        count += 1
        root = tmp_path / str(count)
        root.mkdir()
        git(root, "init", "--quiet", "--initial-branch=main")
        git(root, "config", "core.autocrlf", "false")
        (root / "config").mkdir()
        (root / "config/quality_baseline.v1.json").write_text(
            json.dumps({"protected_patterns": ["config/quality*.json", "legacy/*.py"]}),
            encoding="utf-8",
        )
        (root / "legacy").mkdir()
        (root / "legacy/existing.py").write_text("preserve_old_behavior = True\n", encoding="utf-8")
        (root / "new/nested").mkdir(parents=True)
        (root / "new/nested/evaluator.py").write_text("real_scoring = True\n", encoding="utf-8")
        (root / ".gitignore").write_text("new/ignored/\n", encoding="utf-8")
        if protocol:
            value = {"protocol_id": "p0-02.v2", "protected_patterns": ["new/*.py"]}
            (root / PROTOCOL).write_text(
                json.dumps(value) if protocol is True else "malformed", encoding="utf-8"
            )
        records = {
            mode: value
            or {
                "protocol_id": "p0-02.v2",
                "acceptance_id": "unit-" + mode,
                "manifest_hash": f"{number:064x}",
            }
            for number, (mode, value) in enumerate((accepted or {}).items(), 1)
        }
        if trust:
            (root / TRUST).write_text(
                json.dumps(
                    {
                        "protocol_id": "p0-02.v2",
                        "latest_accepted_baselines": {
                            mode: value["acceptance_id"] for mode, value in records.items()
                        },
                        "accepted_baselines": {
                            value["acceptance_id"]: value["manifest_hash"]
                            for value in records.values()
                        },
                    }
                ),
                encoding="utf-8",
            )
        if index:
            (root / INDEX).write_text(
                json.dumps({"protocol_id": "p0-02.v2", "accepted": records}),
                encoding="utf-8",
            )
        reference = commit(root)
        git(root, "update-ref", "refs/remotes/origin/main", reference)
        return root, reference

    return create


def policy(root, reference, monkeypatch):
    module = script("check_quality_policy")
    monkeypatch.setattr(
        sys, "argv", [module.__file__, "--root", str(root), "--trusted-ref", reference]
    )
    return module.main()


def test_guard_preserves_old_scope_and_loads_extra_only_from_trusted_main(repository, monkeypatch):
    root, ref = repository()
    assert policy(root, ref, monkeypatch) == 0
    (root / "new/nested/evaluator.py").write_text("real_scoring = False\n", encoding="utf-8")
    assert policy(root, ref, monkeypatch) == 3
    # A candidate cannot remove supplemental protection to approve its own edit.
    (root / PROTOCOL).write_text('{"protected_patterns": []}', encoding="utf-8")
    assert policy(root, ref, monkeypatch) == 3
    root, ref = repository(protocol=False, index=False)
    (root / "new/nested/evaluator.py").write_text("not_yet_accepted = True\n", encoding="utf-8")
    assert policy(root, ref, monkeypatch) == 0
    (root / "legacy/existing.py").write_text("preserve_old_behavior = False\n", encoding="utf-8")
    assert policy(root, ref, monkeypatch) == 3


@pytest.mark.parametrize("change", ["add", "delete", "ignored", "delete_policy"])
def test_extra_guard_detects_nested_additions_deletions_and_ignored_files(
    repository, monkeypatch, change
):
    root, ref = repository()
    if change == "delete":
        (root / "new/nested/evaluator.py").unlink()
    elif change == "delete_policy":
        (root / PROTOCOL).unlink()
    elif change == "ignored":
        (root / "new/ignored").mkdir()
        (root / "new/ignored/bypass.py").write_text("cannot_hide = True", encoding="utf-8")
    else:
        (root / "new/nested/added.py").write_text("new_checker = True", encoding="utf-8")
    assert policy(root, ref, monkeypatch) == 3


@pytest.mark.parametrize(
    "value",
    [
        "malformed",
        {"protected_patterns": []},
        {"protected_patterns": "new/*.py"},
        {"protected_patterns": [1]},
        {"protected_patterns": [""]},
    ],
)
def test_malformed_accepted_supplementary_policy_fails_closed(repository, monkeypatch, value):
    root, _ = repository()
    (root / PROTOCOL).write_text(
        value if isinstance(value, str) else json.dumps(value), encoding="utf-8"
    )
    ref = commit(root)
    git(root, "update-ref", "refs/remotes/origin/main", ref)
    with pytest.raises(ValueError):
        policy(root, ref, monkeypatch)


def harness(module, root, monkeypatch, *, execution=0, check=0, completed=True):
    monkeypatch.setattr(module, "__file__", str(root / "scripts/ci_answerability_eval.py"))
    monkeypatch.delenv("ANSWERABILITY_BASE_SHA", raising=False)
    calls = []

    def main(args):
        calls.append(args)
        assert args[:2] == ["--project-root", str(root)]
        if args[2] == "run":
            if completed:
                directory = Path(args[args.index("--out") + 1])
                directory.mkdir(parents=True)
                (directory / "COMPLETED").write_text("sealed", encoding="utf-8")
            return execution
        return check

    monkeypatch.setattr(module, "main", main)
    return calls


@pytest.mark.parametrize("accepted", [{}, {"rule_only": {}}, {"rule_only": {}, "mocked_model": {}}])
def test_ci_uses_trusted_baselines_and_never_candidate_inventory_override(
    repository, monkeypatch, capsys, accepted
):
    root, ref = repository(accepted=accepted)
    # Candidate cannot hide accepted pointers by replacing the local index.
    (root / INDEX).write_text('{"accepted": {}}', encoding="utf-8")
    module = script("ci_answerability_eval")
    calls = harness(module, root, monkeypatch)
    assert module.run_ci() == 0
    checks = [args for args in calls if args[2] == "check"]
    assert len(checks) == 2
    for args, mode in zip(checks, ("rule_only", "mocked_model"), strict=True):
        assert args[args.index("--gate") + 1] == ("regression" if mode in accepted else "inventory")
        assert args[args.index("--candidate-sha") + 1] == ref
        if mode in accepted:
            assert args[args.index("--trusted-ref") + 1] == ref
        else:
            assert "--trusted-ref" not in args
    output = capsys.readouterr().out
    assert ("BOOTSTRAP ONLY" in output) == (len(accepted) < 2)
    assert "not_evaluated" in output


def test_ci_bootstrap_only_when_new_protocol_absent(repository, monkeypatch):
    root, _ = repository(protocol=False, index=False)
    module = script("ci_answerability_eval")
    calls = harness(module, root, monkeypatch)
    assert module.run_ci() == 0
    assert all(
        args[args.index("--gate") + 1] == "inventory" for args in calls if args[2] == "check"
    )


@pytest.mark.parametrize(
    "problem",
    [
        "missing_index",
        "malformed_protocol",
        "wrong_protocol",
        "wrong_index_protocol",
        "invalid_index",
        "unknown_mode",
        "old_ref",
    ],
)
def test_ci_invalid_trusted_state_never_downgrades_to_inventory(repository, monkeypatch, problem):
    root, old = repository(
        index=problem != "missing_index",
        protocol="bad" if problem == "malformed_protocol" else True,
    )
    if problem == "wrong_protocol":
        (root / PROTOCOL).write_text('{"protocol_id": "p0-01.v1"}', encoding="utf-8")
    elif problem == "wrong_index_protocol":
        (root / INDEX).write_text('{"protocol_id": "p0-01.v1", "accepted": {}}', encoding="utf-8")
    elif problem == "invalid_index":
        (root / INDEX).write_text('{"protocol_id": "p0-02.v2", "accepted": []}', encoding="utf-8")
    elif problem == "unknown_mode":
        (root / INDEX).write_text(
            '{"protocol_id": "p0-02.v2", "accepted": {"live": {}}}', encoding="utf-8"
        )
    elif problem == "old_ref":
        (root / "next.txt").write_text("new accepted commit", encoding="utf-8")
    if problem in {
        "wrong_protocol",
        "wrong_index_protocol",
        "invalid_index",
        "unknown_mode",
        "old_ref",
    }:
        ref = commit(root)
        git(root, "update-ref", "refs/remotes/origin/main", ref)
    module = script("ci_answerability_eval")
    calls = harness(module, root, monkeypatch)
    if problem == "old_ref":
        monkeypatch.setenv("ANSWERABILITY_BASE_SHA", old)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        module.run_ci()
    assert calls == []


@pytest.mark.parametrize("execution,check,expected", [(0, 1, 1), (2, 0, 2), (2, 3, 3)])
def test_ci_keeps_execution_and_check_error_priority(
    repository, monkeypatch, execution, check, expected
):
    root, _ = repository()
    module = script("ci_answerability_eval")
    harness(module, root, monkeypatch, execution=execution, check=check)
    assert module.run_ci() == expected


def test_ci_missing_completed_is_error_even_when_runner_returned_zero(repository, monkeypatch):
    root, _ = repository()
    module = script("ci_answerability_eval")
    calls = harness(module, root, monkeypatch, completed=False)
    assert module.run_ci() == 2
    assert len(calls) == 2 and all(args[2] == "run" for args in calls)


@pytest.fixture
def provenance_setup(tmp_path, monkeypatch):
    module = script("write_answerability_provenance")
    root = tmp_path / "reports"
    for mode in ("rule_only", "mocked_model"):
        directory = root / mode
        directory.mkdir(parents=True)
        (directory / "COMPLETED").write_bytes(b"sealed-marker")
        (directory / "manifest.json").write_bytes(b"original-sealed-manifest")
    loaded = []

    def load_run(directory):
        loaded.append(directory)
        return {
            "metadata": {"tested_commit": "a" * 40, "protocol_id": "p0-02.v2"},
            "manifest_hash": "b" * 64,
        }

    monkeypatch.setattr(module, "load_run", load_run)
    values = {
        "GITHUB_REPOSITORY": "owner/repository",
        "GITHUB_WORKFLOW_SHA": "c" * 40,
        "GITHUB_RUN_ID": "100",
        "GITHUB_RUN_ATTEMPT": "2",
        "ANSWERABILITY_ARTIFACT_ID": "200",
        "ANSWERABILITY_ARTIFACT_DIGEST": "sha256:" + "d" * 64,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    output = tmp_path / "outer/index.json"
    monkeypatch.setattr(sys, "argv", [module.__file__, "--root", str(root), "--out", str(output)])
    return module, root, output, loaded


def test_provenance_binds_upload_without_changing_any_report_bytes(provenance_setup):
    module, root, output, loaded = provenance_setup
    before = {
        p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    module.main()
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["schema_version"] == "answerability-provenance.v2"
    assert len(value["reports"]) == 2 and len(loaded) == 2
    assert {r["artifact_prefix"] for r in value["reports"]} == {"rule_only", "mocked_model"}
    assert all(
        r["provenance"]["artifact_id"] == "200" and r["provenance"]["tested_commit"] == "a" * 40
        for r in value["reports"]
    )
    assert before == {
        p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    with pytest.raises(FileExistsError):
        module.main()


@pytest.mark.parametrize(
    "name",
    [
        "GITHUB_REPOSITORY",
        "GITHUB_WORKFLOW_SHA",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "ANSWERABILITY_ARTIFACT_ID",
        "ANSWERABILITY_ARTIFACT_DIGEST",
    ],
)
def test_provenance_requires_every_nonempty_upload_and_workflow_output(
    provenance_setup, monkeypatch, name
):
    module, _, output, _ = provenance_setup
    monkeypatch.setenv(name, "  ")
    with pytest.raises(ValueError, match="nonempty"):
        module.main()
    assert not output.exists()


def test_provenance_rejects_no_completed_reports(provenance_setup):
    module, root, output, _ = provenance_setup
    for marker in root.glob("*/COMPLETED"):
        marker.unlink()
    with pytest.raises(ValueError, match="no completed"):
        module.main()
    assert not output.exists()


def test_provenance_cannot_write_inside_sealed_report(provenance_setup, monkeypatch):
    module, root, _, _ = provenance_setup
    output = root / "rule_only/extra-index.json"
    monkeypatch.setattr(sys, "argv", [module.__file__, "--root", str(root), "--out", str(output)])
    with pytest.raises(ValueError, match="outside sealed"):
        module.main()
    assert not output.exists()


def test_provenance_refuses_invalid_report_before_creating_index(provenance_setup, monkeypatch):
    module, _, output, _ = provenance_setup

    def invalid(_):
        raise ValueError("invalid report bytes")

    monkeypatch.setattr(module, "load_run", invalid)
    with pytest.raises(ValueError, match="invalid report"):
        module.main()
    assert not output.exists()


def test_workflow_enforces_guard_before_candidate_execution_and_separate_provenance():
    # BaseLoader preserves YAML's 'on' event key instead of treating it as bool.
    workflow = yaml.load(
        (ROOT / ".github/workflows/answerability-eval.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"push", "pull_request", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"answerability"}
    job = workflow["jobs"]["answerability"]
    assert "if" not in job and job["env"]["ALLOW_NETWORK"] == "false"
    steps = job["steps"]
    guard = next(s for s in steps if s.get("id") == "policy")
    assert steps.index(guard) == 1
    assert 'git show "$base_ref:scripts/check_quality_policy.py"' in guard["run"]
    assert 'python "$RUNNER_TEMP/accepted-answerability-policy.py"' in guard["run"]
    assert "python scripts/check_quality_policy.py" not in guard["run"]
    assert "refs/remotes/origin/main" in guard["run"]
    assert (
        next(s for s in steps if s.get("uses", "").startswith("actions/setup-python"))["with"][
            "python-version"
        ]
        == "3.12.13"
    )
    assert (
        next(s for s in steps if s.get("uses", "").startswith("astral-sh/setup-uv"))["with"][
            "version"
        ]
        == "0.12.0"
    )
    assert (
        next(s for s in steps if s.get("id") == "dependencies")["run"]
        == "uv sync --locked --extra dev"
    )
    artifact = next(s for s in steps if s.get("id") == "answerability-artifact")
    provenance = next(s for s in steps if s.get("id") == "provenance")
    assert steps.index(artifact) < steps.index(provenance)
    assert "steps.policy.outcome == 'success'" in provenance["if"]
    assert "steps.dependencies.outcome == 'success'" in provenance["if"]
    assert "ANSWERABILITY_ARTIFACT_DIGEST" in provenance["env"]
    assert "--out data/runtime/answerability-provenance/index.json" in provenance["run"]
    assert steps[-1]["if"] == "always() && steps.provenance.outcome == 'success'"


def test_v2_guard_keeps_v1_archive_scope(repository, monkeypatch):
    root, _ = repository()
    (root / "config/quality_answerability.v1.json").write_text(
        json.dumps({"protocol_id": "p0-02.v1", "protected_patterns": ["archive/*.json"]}),
        encoding="utf-8",
    )
    (root / "archive").mkdir()
    (root / "archive/original.json").write_text('{"value": 1}', encoding="utf-8")
    reference = commit(root)
    git(root, "update-ref", "refs/remotes/origin/main", reference)
    assert policy(root, reference, monkeypatch) == 0
    (root / "archive/original.json").write_text('{"value": 2}', encoding="utf-8")
    assert policy(root, reference, monkeypatch) == 3


def test_v2_guard_cannot_drop_protection_by_selecting_v1(repository, monkeypatch):
    root, reference = repository()
    (root / PROTOCOL).unlink()
    (root / "config/quality_answerability.v1.json").write_text(
        json.dumps({"protocol_id": "p0-02.v1", "protected_patterns": ["legacy/*.py"]}),
        encoding="utf-8",
    )
    (root / "new/nested/evaluator.py").write_text("weakened = True", encoding="utf-8")
    assert policy(root, reference, monkeypatch) == 3


def test_artifact_writer_rejects_inactive_or_mixed_report_versions(provenance_setup, monkeypatch):
    module, _, output, _ = provenance_setup
    monkeypatch.setattr(
        module,
        "load_run",
        lambda path: {
            "metadata": {"tested_commit": "a" * 40, "protocol_id": "p0-02.v1"},
            "manifest_hash": "b" * 64,
        },
    )
    with pytest.raises(ValueError, match="active protocol"):
        module.main()
    assert not output.exists()


@pytest.mark.parametrize(
    "problem",
    [
        "missing_trust",
        "wrong_trust_protocol",
        "missing_latest",
        "missing_registered",
        "malformed_latest",
        "malformed_registered",
        "empty_index",
        "missing_mode",
        "missing_latest_mode",
        "latest_mismatch",
        "manifest_mismatch",
        "unregistered_id",
        "missing_record_id",
        "missing_record_manifest",
        "wrong_record_protocol",
        "invalid_record",
        "unsafe_record_path",
        "missing_record_path",
        "all_latest_cleared",
        "duplicate_ids",
    ],
)
def test_ci_rejects_every_index_registry_drift_before_executing_candidate(
    repository, monkeypatch, problem
):
    root, _ = repository(accepted={"rule_only": {}, "mocked_model": {}})
    index = json.loads((root / INDEX).read_text("utf-8"))
    trust = json.loads((root / TRUST).read_text("utf-8"))
    record = index["accepted"]["rule_only"]
    if problem == "missing_trust":
        (root / TRUST).unlink()
    elif problem == "wrong_trust_protocol":
        trust["protocol_id"] = "p0-02.v1"
    elif problem == "missing_latest":
        trust.pop("latest_accepted_baselines")
    elif problem == "missing_registered":
        trust.pop("accepted_baselines")
    elif problem == "malformed_latest":
        trust["latest_accepted_baselines"] = []
    elif problem == "malformed_registered":
        trust["accepted_baselines"] = []
    elif problem == "empty_index":
        index["accepted"] = {}
    elif problem == "missing_mode":
        index["accepted"].pop("mocked_model")
    elif problem == "missing_latest_mode":
        trust["latest_accepted_baselines"].pop("mocked_model")
    elif problem == "latest_mismatch":
        trust["latest_accepted_baselines"]["rule_only"] = "other"
    elif problem == "manifest_mismatch":
        record["manifest_hash"] = "f" * 64
    elif problem == "unregistered_id":
        trust["accepted_baselines"].pop(record["acceptance_id"])
    elif problem == "missing_record_id":
        record.pop("acceptance_id")
    elif problem == "missing_record_manifest":
        record.pop("manifest_hash")
    elif problem == "wrong_record_protocol":
        record["protocol_id"] = "p0-02.v1"
    elif problem == "invalid_record":
        index["accepted"]["rule_only"] = []
    elif problem == "unsafe_record_path":
        index["accepted"]["rule_only"] = "../untrusted.json"
    elif problem == "missing_record_path":
        index["accepted"]["rule_only"] = "config/absent.json"
    elif problem == "all_latest_cleared":
        index["accepted"] = {}
        trust["latest_accepted_baselines"] = {}
    else:
        index["accepted"]["mocked_model"] = dict(record)
        trust["latest_accepted_baselines"]["mocked_model"] = record["acceptance_id"]
    (root / INDEX).write_text(json.dumps(index), encoding="utf-8")
    if problem != "missing_trust":
        (root / TRUST).write_text(json.dumps(trust), encoding="utf-8")
    ref = commit(root)
    git(root, "update-ref", "refs/remotes/origin/main", ref)
    module = script("ci_answerability_eval")
    calls = harness(module, root, monkeypatch)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        module.run_ci()
    assert calls == []


def test_ci_reads_path_records_and_trust_only_from_current_accepted_git(repository, monkeypatch):
    root, _ = repository(accepted={"rule_only": {}, "mocked_model": {}})
    index = json.loads((root / INDEX).read_text("utf-8"))
    record_path = "config/unit-rule-baseline.json"
    (root / record_path).write_text(json.dumps(index["accepted"]["rule_only"]), encoding="utf-8")
    index["accepted"]["rule_only"] = record_path
    (root / INDEX).write_text(json.dumps(index), encoding="utf-8")
    ref = commit(root)
    git(root, "update-ref", "refs/remotes/origin/main", ref)
    # Candidate local files cannot select a weaker accepted state.
    (root / record_path).write_text("{}", encoding="utf-8")
    (root / TRUST).write_text("{}", encoding="utf-8")
    module = script("ci_answerability_eval")
    calls = harness(module, root, monkeypatch)
    assert module.run_ci() == 0
    assert all(
        args[args.index("--gate") + 1] == "regression" for args in calls if args[2] == "check"
    )
