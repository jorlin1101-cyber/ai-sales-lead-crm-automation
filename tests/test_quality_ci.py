"""Executable, offline checks for bootstrap and trusted-policy CI scripts."""

import importlib.util
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = ROOT / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location("test_import_" + name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(root, name):
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Quality Test",
        "-c",
        "user.email=quality@example.test",
        "commit",
        "--quiet",
        "-m",
        name,
    )
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repository_factory(tmp_path):
    roots = []

    def create(*, protocol=True, index=True, accepted=None):
        root = tmp_path / f"repository-{len(roots)}"
        roots.append(root)
        root.mkdir()
        git(root, "init", "--quiet", "--initial-branch=main")
        git(root, "config", "core.autocrlf", "false")
        (root / "src").mkdir()
        (root / "src/evaluator.py").write_text("accepted = True\n", encoding="utf-8")
        (root / "config").mkdir()
        if protocol:
            value = {"protected_patterns": ["config/quality*.json", "src/evaluator.py"]}
            (root / "config/quality_baseline.v1.json").write_text(
                json.dumps(value) if protocol is True else "malformed", encoding="utf-8"
            )
        if index:
            (root / "config/quality_baseline_index.v1.json").write_text(
                json.dumps({"accepted": accepted or {}}), encoding="utf-8"
            )
        reference = commit(root, "accepted protocol")
        git(root, "update-ref", "refs/remotes/origin/main", reference)
        return root, reference

    return create


def policy(module, root, reference, monkeypatch, *, bootstrap=False):
    args = [module.__file__, "--root", str(root), "--trusted-ref", reference]
    if bootstrap:
        args.append("--bootstrap")
    monkeypatch.setattr(sys, "argv", args)
    return module.main()


def test_policy_accepts_same_logical_text_and_rejects_scoring_edits(
    repository_factory, monkeypatch, capsys
):
    root, reference = repository_factory()
    module = load_script("check_quality_policy")
    (root / "src/evaluator.py").write_bytes(b"accepted = True\r\n")
    assert policy(module, root, reference, monkeypatch) == 0
    assert json.loads(capsys.readouterr().out)["trusted_ref"] == reference
    (root / "src/evaluator.py").write_text("accepted = False\n", encoding="utf-8")
    assert policy(module, root, reference, monkeypatch) == 3
    assert (
        "src/evaluator.py"
        in json.loads(capsys.readouterr().out)["protocol_upgrade_requires_review"]
    )


@pytest.mark.parametrize("change", ["addition", "deletion"])
def test_policy_detects_new_or_removed_protected_files(repository_factory, monkeypatch, change):
    root, reference = repository_factory()
    module = load_script("check_quality_policy")
    if change == "addition":
        (root / "config/quality_loophole.json").write_text("{}", encoding="utf-8")
    else:
        (root / "src/evaluator.py").unlink()
    assert policy(module, root, reference, monkeypatch) == 3


def test_bootstrap_is_only_allowed_before_the_first_protocol(
    repository_factory, monkeypatch, capsys
):
    module = load_script("check_quality_policy")
    root, reference = repository_factory(protocol=False, index=False)
    assert policy(module, root, reference, monkeypatch, bootstrap=True) == 0
    assert "release is not approved" in capsys.readouterr().out
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        policy(module, root, reference, monkeypatch)
    root, reference = repository_factory()
    with pytest.raises(ValueError, match="bootstrap"):
        policy(module, root, reference, monkeypatch, bootstrap=True)


def test_malformed_protocol_is_never_a_bootstrap_permission(repository_factory, monkeypatch):
    root, reference = repository_factory(protocol="invalid")
    module = load_script("check_quality_policy")
    with pytest.raises(ValueError):
        policy(module, root, reference, monkeypatch, bootstrap=True)


def test_old_ancestor_cannot_replace_the_current_accepted_policy(repository_factory, monkeypatch):
    root, old = repository_factory()
    (root / "accepted-change.txt").write_text("new accepted commit", encoding="utf-8")
    current = commit(root, "advance accepted main")
    git(root, "update-ref", "refs/remotes/origin/main", current)
    module = load_script("check_quality_policy")
    with pytest.raises(ValueError):
        policy(module, root, old, monkeypatch)


def ci_harness(module, root, monkeypatch, *, execution=0, check=0, seal=True):
    monkeypatch.setattr(module, "__file__", str(root / "scripts/ci_quality_eval.py"))
    monkeypatch.delenv("QUALITY_BASE_SHA", raising=False)
    calls = []

    def main(args):
        calls.append(args)
        if args[0] == "run":
            if seal:
                directory = Path(args[args.index("--out") + 1])
                directory.mkdir(parents=True)
                (directory / "COMPLETED").write_text("sealed", encoding="utf-8")
            return execution
        return check

    monkeypatch.setattr(module, "main", main)
    return calls


def test_ci_uses_inventory_for_bootstrap_and_regression_for_each_accepted_mode(
    repository_factory, monkeypatch, capsys
):
    module = load_script("ci_quality_eval")
    root, _ = repository_factory()
    calls = ci_harness(module, root, monkeypatch)
    assert module.run_ci() == 0
    checks = [args for args in calls if args[0] == "check"]
    assert len(checks) == 2
    assert all(args[args.index("--gate") + 1] == "inventory" for args in checks)
    assert "BOOTSTRAP" in capsys.readouterr().out

    root, reference = repository_factory(accepted={"rule_only": {}, "mocked_model": {}})
    calls = ci_harness(module, root, monkeypatch)
    monkeypatch.setenv("QUALITY_BASE_SHA", reference)
    assert module.run_ci() == 0
    checks = [args for args in calls if args[0] == "check"]
    assert all(args[args.index("--gate") + 1] == "regression" for args in checks)
    assert all(args[args.index("--trusted-ref") + 1] == reference for args in checks)
    assert all(args[args.index("--candidate-sha") + 1] == reference for args in checks)


def test_ci_can_bootstrap_without_any_prior_protocol(repository_factory, monkeypatch):
    root, _ = repository_factory(protocol=False, index=False)
    module = load_script("ci_quality_eval")
    calls = ci_harness(module, root, monkeypatch)
    assert module.run_ci() == 0
    assert all(
        args[args.index("--gate") + 1] == "inventory" for args in calls if args[0] == "check"
    )


def test_ci_missing_index_under_existing_protocol_is_not_bootstrap(repository_factory, monkeypatch):
    root, _ = repository_factory(index=False)
    module = load_script("ci_quality_eval")
    calls = ci_harness(module, root, monkeypatch)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        module.run_ci()
    assert calls == []


def test_ci_malformed_accepted_protocol_cannot_fall_back_to_inventory(
    repository_factory, monkeypatch
):
    root, _ = repository_factory(protocol="invalid", index=False)
    module = load_script("ci_quality_eval")
    calls = ci_harness(module, root, monkeypatch)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        module.run_ci()
    assert calls == []


@pytest.mark.parametrize("execution,check,expected", [(0, 1, 1), (2, 0, 2), (2, 3, 3)])
def test_ci_propagates_execution_and_gate_failures(
    repository_factory, monkeypatch, execution, check, expected
):
    root, _ = repository_factory(accepted={"rule_only": {}, "mocked_model": {}})
    module = load_script("ci_quality_eval")
    ci_harness(module, root, monkeypatch, execution=execution, check=check)
    assert module.run_ci() == expected


@pytest.mark.parametrize("execution", [0, 2])
def test_ci_missing_completion_marker_is_never_green(repository_factory, monkeypatch, execution):
    root, _ = repository_factory()
    module = load_script("ci_quality_eval")
    calls = ci_harness(module, root, monkeypatch, execution=execution, seal=False)
    assert module.run_ci() == 2
    assert not any(args[0] == "check" for args in calls)


@pytest.mark.parametrize("reference_kind", ["stale", "missing"])
def test_ci_rejects_an_unaccepted_reference_before_any_bootstrap(
    repository_factory, monkeypatch, reference_kind
):
    root, old = repository_factory(protocol=False, index=False)
    (root / "next-accepted.txt").write_text("new accepted head", encoding="utf-8")
    current = commit(root, "next accepted head")
    git(root, "update-ref", "refs/remotes/origin/main", current)
    module = load_script("ci_quality_eval")
    calls = ci_harness(module, root, monkeypatch)
    reference = old if reference_kind == "stale" else "0" * 40
    monkeypatch.setenv("QUALITY_BASE_SHA", reference)
    with pytest.raises(ValueError):
        module.run_ci()
    assert calls == []


def test_outdated_lock_export_cannot_fall_back_to_existing_constraints(monkeypatch):
    commands = []

    def outdated_lock(args, **kwargs):
        commands.append((args, kwargs))
        raise subprocess.CalledProcessError(2, args, stderr="lockfile needs update")

    monkeypatch.setattr(subprocess, "run", outdated_lock)
    with pytest.raises(subprocess.CalledProcessError) as error:
        runpy.run_path(str(ROOT / "scripts/check_quality_dependencies.py"), run_name="__main__")
    assert error.value.returncode == 2
    assert commands[0][0][:3] == ["uv", "export", "--locked"]
    assert "--offline" in commands[0][0]
    assert commands[0][1]["check"] is True


@pytest.mark.parametrize("matches,expected_exit", [(True, 0), (False, 1)])
def test_dependency_script_exit_tracks_export_consistency(
    monkeypatch, capsys, matches, expected_exit
):
    frozen = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    exported = frozen if matches else frozen + "\ndefinitely-unfrozen-package==0.0.0\n"

    def export(args, **kwargs):
        assert "--locked" in args and "--offline" in args
        return subprocess.CompletedProcess(args, 0, stdout=exported)

    monkeypatch.setattr(subprocess, "run", export)
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(ROOT / "scripts/check_quality_dependencies.py"), run_name="__main__")
    assert error.value.code == expected_exit
    output = capsys.readouterr().out
    assert ("match uv.lock" if matches else "differ from uv.lock") in output


PROVENANCE_ENVIRONMENT = {
    "GITHUB_REPOSITORY": "example/quality-project",
    "GITHUB_WORKFLOW_SHA": "a" * 40,
    "GITHUB_RUN_ID": "123",
    "GITHUB_RUN_ATTEMPT": "1",
    "QUALITY_ARTIFACT_ID": "456",
    "QUALITY_ARTIFACT_DIGEST": "sha256:" + "b" * 64,
}


@pytest.fixture
def provenance_harness(tmp_path, monkeypatch):
    module = load_script("write_quality_provenance")
    root = tmp_path / "sealed-runs"
    root.mkdir()
    reports = {}
    for mode in ("rule_only", "mocked_model"):
        directory = root / mode
        directory.mkdir()
        (directory / "COMPLETED").write_bytes(b"original completion marker")
        (directory / "manifest.json").write_bytes(b'{"original":"manifest"}')
        (directory / "assertions.jsonl").write_bytes(b'{"behavior_status":"fail"}\n')
        reports[directory] = {
            "metadata": {"tested_commit": "a" * 40, "mode": mode},
            "manifest_hash": ("c" if mode == "rule_only" else "d") * 64,
        }
    incomplete = root / "interrupted-run"
    incomplete.mkdir()
    (incomplete / "manifest.json").write_bytes(b"unfinished diagnostic")
    output = tmp_path / "outer-provenance/index.json"
    for key, value in PROVENANCE_ENVIRONMENT.items():
        monkeypatch.setenv(key, value)
    calls = []

    def load(directory):
        calls.append(directory)
        return reports[directory]

    monkeypatch.setattr(module, "load_run", load)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__file__,
            "--root",
            str(root),
            "--out",
            str(output),
        ],
    )
    return {"module": module, "root": root, "output": output, "reports": reports, "calls": calls}


def report_bytes(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_provenance_is_an_outer_index_and_preserves_every_sealed_byte(provenance_harness):
    fixture = provenance_harness
    before = report_bytes(fixture["root"])
    fixture["module"].main()
    assert report_bytes(fixture["root"]) == before
    payload = json.loads(fixture["output"].read_text(encoding="utf-8"))
    assert payload["schema_version"] == "p0-quality-provenance.v1"
    assert [entry["artifact_prefix"] for entry in payload["reports"]] == [
        "mocked_model",
        "rule_only",
    ]
    assert set(fixture["calls"]) == set(fixture["reports"])
    for entry in payload["reports"]:
        provenance = entry["provenance"]
        assert provenance["artifact_id"] == PROVENANCE_ENVIRONMENT["QUALITY_ARTIFACT_ID"]
        assert provenance["artifact_digest"] == PROVENANCE_ENVIRONMENT["QUALITY_ARTIFACT_DIGEST"]
        assert provenance["repository"] == PROVENANCE_ENVIRONMENT["GITHUB_REPOSITORY"]
        assert provenance["tested_commit"] == "a" * 40
        assert (
            provenance["manifest_hash"]
            == fixture["reports"][Path(entry["directory"])]["manifest_hash"]
        )


@pytest.mark.parametrize("key", list(PROVENANCE_ENVIRONMENT))
@pytest.mark.parametrize("state", ["absent", "empty"])
def test_provenance_requires_every_upload_and_workflow_output(
    provenance_harness, monkeypatch, key, state
):
    fixture = provenance_harness
    if state == "absent":
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, "")
    before = report_bytes(fixture["root"])
    with pytest.raises(ValueError):
        fixture["module"].main()
    assert not fixture["output"].exists()
    assert report_bytes(fixture["root"]) == before


def test_provenance_does_not_publish_an_empty_index(provenance_harness):
    fixture = provenance_harness
    for directory in fixture["reports"]:
        (directory / "COMPLETED").unlink()
    with pytest.raises(ValueError):
        fixture["module"].main()
    assert fixture["calls"] == []
    assert not fixture["output"].exists()


def test_provenance_never_overwrites_an_existing_index(provenance_harness):
    fixture = provenance_harness
    fixture["output"].parent.mkdir()
    fixture["output"].write_bytes(b"existing accepted index")
    before = report_bytes(fixture["root"])
    with pytest.raises(FileExistsError):
        fixture["module"].main()
    assert fixture["output"].read_bytes() == b"existing accepted index"
    assert report_bytes(fixture["root"]) == before


def test_provenance_propagates_manifest_failure_without_writing_index(
    provenance_harness, monkeypatch
):
    fixture = provenance_harness

    def invalid_report(directory):
        raise ValueError("sealed manifest verification failed")

    monkeypatch.setattr(fixture["module"], "load_run", invalid_report)
    with pytest.raises(ValueError, match="manifest"):
        fixture["module"].main()
    assert not fixture["output"].exists()


def test_provenance_requires_an_explicit_output_path(provenance_harness, monkeypatch):
    fixture = provenance_harness
    monkeypatch.setattr(
        sys,
        "argv",
        [
            fixture["module"].__file__,
            "--root",
            str(fixture["root"]),
        ],
    )
    with pytest.raises(SystemExit) as error:
        fixture["module"].main()
    assert error.value.code == 2
    assert not fixture["output"].exists()


def test_sealed_baseline_bytes_survive_windows_git_checkout(repository_factory, tmp_path):
    root, _ = repository_factory()
    git(root, "config", "core.autocrlf", "true")
    (root / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    relative = "reports/quality/baselines/p0-01.v1/sample/run/manifest.json"
    source = root / relative
    source.parent.mkdir(parents=True)
    payload = b'{"sealed":true}\n'
    source.write_bytes(payload)
    commit(root, "sealed report fixture")
    checkout = tmp_path / "windows-checkout"
    git(root, "checkout-index", "--all", "--prefix=" + checkout.as_posix() + "/")
    assert (checkout / relative).read_bytes() == payload
    assert git(root, "check-attr", "text", "--", relative).endswith("text: unset")


@pytest.mark.parametrize("checker", ["standalone", "context"])
@pytest.mark.parametrize(
    "change", ["unchanged", "modify", "delete", "add", "ignored_add", "unprotected_add"]
)
def test_policy_entrypoints_keep_nested_fnmatch_protection(
    repository_factory, monkeypatch, capsys, checker, change
):
    from lead_cleaner.evaluation.quality_context import verify_protected_files

    root, _ = repository_factory()
    protocol_path = root / "config/quality_baseline.v1.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol["protected_patterns"].append("data/rag_eval/*.json*")
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    nested_name = "data/rag_eval/review/bge-m3-v4-unjudged-review.json"
    nested = root / nested_name
    nested.parent.mkdir(parents=True)
    nested.write_text('{"accepted": true}\n', encoding="utf-8")
    ignored_name = "data/rag_eval/review/ignored.json"
    (root / ".gitignore").write_text(ignored_name + "\n", encoding="utf-8")
    reference = commit(root, "protect nested review files")
    git(root, "update-ref", "refs/remotes/origin/main", reference)

    changed_name = nested_name
    if change == "modify":
        nested.write_text('{"accepted": false}\n', encoding="utf-8")
    elif change == "delete":
        nested.unlink()
    elif change in {"add", "ignored_add", "unprotected_add"}:
        changed_name = {
            "add": "data/rag_eval/review/new-review.jsonl",
            "ignored_add": ignored_name,
            "unprotected_add": "data/rag_eval/review/notes.txt",
        }[change]
        (root / changed_name).write_text("new content\n", encoding="utf-8")
        if change == "ignored_add":
            assert git(root, "check-ignore", changed_name) == changed_name

    passes = change in {"unchanged", "unprotected_add"}
    if checker == "standalone":
        module = load_script("check_quality_policy")
        assert policy(module, root, reference, monkeypatch) == (0 if passes else 3)
        output = json.loads(capsys.readouterr().out)
        if passes:
            assert output["protected_files_verified"] == 4
        else:
            assert output["protocol_upgrade_requires_review"] == [changed_name]
    elif passes:
        assert nested_name in verify_protected_files(root, reference)["verified_files"]
    else:
        with pytest.raises(ValueError, match="upgrade requires review") as error:
            verify_protected_files(root, reference)
        assert changed_name in str(error.value)


@pytest.mark.parametrize("checker", ["standalone", "context"])
def test_policy_enumeration_uses_fixed_prefix_and_identical_fnmatch_semantics(
    repository_factory, monkeypatch, checker
):
    from lead_cleaner.evaluation import quality_context

    root, _ = repository_factory()
    names = [
        "data/rag_eval/review/nested.json",
        "src/grading/nested/rules1.py",
        "src/grading/nested/rules1.txt",
        ".venv/large/dependency.json",
        "data/runtime/large/output.json",
    ]
    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture", encoding="utf-8")
    patterns = [
        "data/rag_eval/*.json*",
        "src/grading*/rules?.[pj][sy]",
        "config/quality_baseline.v1.json",
        "missing/directory/*.json",
    ]
    original = Path.rglob
    visited = []

    def scoped_rglob(directory, pattern):
        prefix = directory.relative_to(root).as_posix()
        assert prefix in {"data/rag_eval", "src", "missing/directory"}
        visited.append(prefix)
        return original(directory, pattern)

    monkeypatch.setattr(Path, "rglob", scoped_rglob)
    module = load_script("check_quality_policy") if checker == "standalone" else quality_context
    assert module._protected_worktree_files(root, patterns) == {
        "data/rag_eval/review/nested.json",
        "src/grading/nested/rules1.py",
        "config/quality_baseline.v1.json",
    }
    assert visited == ["data/rag_eval", "src", "missing/directory"]
