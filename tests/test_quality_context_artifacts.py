"""Offline tests of trusted Git anchors and GitHub artifact verification."""

import base64
from copy import deepcopy
import hashlib
import io
import json
import subprocess
import warnings
import zipfile

import pytest

from lead_cleaner.evaluation import quality_context
from lead_cleaner.evaluation.quality_context import load_trust_context, verify_github_artifacts
from lead_cleaner.evaluation.quality_schema import content_hash


WORKFLOW_PATH = ".github/workflows/quality.yml"
WORKFLOW = "name: accepted-quality\non: workflow_dispatch\n"
REPOSITORY = "example/quality-project"


def git_at(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit_files(root, message):
    git_at(root, "add", ".")
    git_at(
        root,
        "-c",
        "user.name=Quality Test",
        "-c",
        "user.email=quality@example.test",
        "commit",
        "--quiet",
        "-m",
        message,
    )
    return git_at(root, "rev-parse", "HEAD")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git_at(root, "init", "--quiet", "--initial-branch=main")
    git_at(root, "config", "core.autocrlf", "false")
    trust = {
        "repository": REPOSITORY,
        "approved_workflow_paths": [WORKFLOW_PATH],
        "known_issues_hash": "untrusted-self-assertion",
        "verified_artifacts": ["untrusted-self-assertion"],
    }
    issues = [{"issue_id": "known", "status": "open"}]
    write_json(root / "config/quality_trust.v1.json", trust)
    write_json(root / "config/quality_known_issues.v1.json", {"issues": issues})
    workflow = root / WORKFLOW_PATH
    workflow.parent.mkdir(parents=True)
    workflow.write_text(WORKFLOW, encoding="utf-8")
    trusted_ref = commit_files(root, "accepted trust")
    git_at(root, "update-ref", "refs/remotes/origin/main", trusted_ref)
    return {"root": root, "trusted_ref": trusted_ref, "trust": trust, "issues": issues}


def zip_bytes(files):
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(stream, "w") as archive:
            for name, content in files:
                archive.writestr(name, content)
    return stream.getvalue()


@pytest.fixture
def artifact(repository, tmp_path):
    directory = tmp_path / "report"
    directory.mkdir()
    files = {
        "manifest.json": b'{"run_id":"run-1","files":["assertions.jsonl"]}',
        "assertions.jsonl": b'{"behavior_status":"pass"}\n',
        "COMPLETED": b"sealed-manifest-hash",
    }
    for name, content in files.items():
        (directory / name).write_bytes(content)
    # A directory is not a sealed report file and should not be read as one.
    (directory / "empty-directory").mkdir()
    raw = zip_bytes(list(files.items()))
    digest = hashlib.sha256(raw).hexdigest()
    commit = repository["trusted_ref"]
    provenance = {
        "repository": REPOSITORY,
        "artifact_id": 42,
        "run_id": 7,
        "attempt": 1,
        "tested_commit": commit,
        "workflow_sha": commit,
        "artifact_digest": "sha256:" + digest,
        "manifest_hash": hashlib.sha256(files["manifest.json"]).hexdigest(),
    }
    artifact_payload = {"expired": False, "workflow_run": {"id": 7}, "digest": "sha256:" + digest}
    run_payload = {
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "head_sha": commit,
        "run_attempt": 1,
        "path": WORKFLOW_PATH + "@main",
    }
    endpoints = {
        f"repos/{REPOSITORY}/actions/artifacts/42": json.dumps(artifact_payload).encode(),
        f"repos/{REPOSITORY}/actions/runs/7": json.dumps(run_payload).encode(),
        f"repos/{REPOSITORY}/contents/{WORKFLOW_PATH}?ref={commit}": json.dumps(
            {"content": base64.b64encode(WORKFLOW.encode()).decode()}
        ).encode(),
        f"repos/{REPOSITORY}/actions/artifacts/42/zip": raw,
    }
    entry = {"directory": str(directory), "provenance": provenance}
    return repository | {
        "directory": directory,
        "files": files,
        "entry": entry,
        "endpoints": endpoints,
        "artifact": artifact_payload,
        "run": run_payload,
    }


def getter_for(fixture):
    calls = []

    def getter(endpoint):
        calls.append(endpoint)
        # Unknown endpoints fail locally; the test can never fall through to network.
        return fixture["endpoints"][endpoint]

    return getter, calls


def verify(fixture):
    getter, _ = getter_for(fixture)
    return verify_github_artifacts(
        fixture["root"], fixture["trusted_ref"], [fixture["entry"]], getter=getter
    )


def replace_response(fixture, resource, value):
    identifier = 42 if resource == "artifacts" else 7
    endpoint = f"repos/{REPOSITORY}/actions/{resource}/{identifier}"
    fixture["endpoints"][endpoint] = json.dumps(value).encode()


def replace_archive(fixture, files):
    raw = zip_bytes(files)
    digest = hashlib.sha256(raw).hexdigest()
    fixture["endpoints"][f"repos/{REPOSITORY}/actions/artifacts/42/zip"] = raw
    fixture["entry"]["provenance"]["artifact_digest"] = "sha256:" + digest
    fixture["artifact"]["digest"] = "sha256:" + digest
    replace_response(fixture, "artifacts", fixture["artifact"])


def test_trust_comes_from_an_accepted_remote_ancestor_not_the_worktree(repository):
    root = repository["root"]
    write_json(root / "config/quality_trust.v1.json", {"repository": "attacker/changed"})
    write_json(root / "config/quality_known_issues.v1.json", {"issues": []})
    trusted = load_trust_context(root, repository["trusted_ref"])
    assert trusted["repository"] == REPOSITORY
    assert trusted["known_issues_hash"] == content_hash(repository["issues"])
    assert trusted["verified_artifacts"] == []


def test_unaccepted_candidate_is_not_a_trust_anchor(repository):
    (repository["root"] / "candidate.txt").write_text("unreviewed", encoding="utf-8")
    candidate = commit_files(repository["root"], "unaccepted candidate")
    with pytest.raises(ValueError, match="current accepted"):
        load_trust_context(repository["root"], candidate)


def test_ancestor_check_does_not_replace_full_sha_requirement(repository):
    with pytest.raises(ValueError, match="current accepted"):
        load_trust_context(repository["root"], "HEAD")


def test_artifact_success_binds_archive_workflow_commit_and_manifest(artifact):
    getter, calls = getter_for(artifact)
    result = verify_github_artifacts(
        artifact["root"], artifact["trusted_ref"], [artifact["entry"]], getter=getter
    )
    assert result == [artifact["entry"]["provenance"]]
    assert len(calls) == 4
    assert calls[-1].endswith("/zip")


def test_dispatch_nested_artifact_and_crlf_workflow_are_supported(artifact):
    artifact["run"]["event"] = "workflow_dispatch"
    replace_response(artifact, "runs", artifact["run"])
    artifact["entry"]["artifact_prefix"] = "quality/mock"
    replace_archive(
        artifact, [("quality/mock/" + name, value) for name, value in artifact["files"].items()]
    )
    endpoint = f"repos/{REPOSITORY}/contents/{WORKFLOW_PATH}?ref={artifact['trusted_ref']}"
    artifact["endpoints"][endpoint] = json.dumps(
        {"content": base64.b64encode(WORKFLOW.replace("\n", "\r\n").encode()).decode()}
    ).encode()
    # Digest prefix is optional, but both independently supplied digests still match.
    artifact["entry"]["provenance"]["artifact_digest"] = artifact["entry"]["provenance"][
        "artifact_digest"
    ].removeprefix("sha256:")
    assert verify(artifact) == [artifact["entry"]["provenance"]]


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("repository", "repository mismatch"),
        ("artifact_id", "invalid artifact id"),
        ("expired", "expired or run mismatch"),
        ("run_id", "expired or run mismatch"),
        ("event", "exact-commit"),
        ("status", "complete successfully"),
        ("conclusion", "complete successfully"),
        ("tested_commit", "candidate or attempt mismatch"),
        ("attempt", "candidate or attempt mismatch"),
        ("workflow_sha", "workflow commit mismatch"),
        ("workflow_path", "unapproved workflow"),
        ("workflow_content", "differs from accepted protocol"),
        ("provenance_digest", "digest mismatch"),
        ("server_digest", "digest mismatch"),
        ("manifest_hash", "provenance manifest mismatch"),
    ],
)
def test_artifact_source_failures_are_rejected(artifact, mutation, message):
    provenance = artifact["entry"]["provenance"]
    if mutation == "repository":
        provenance["repository"] = "other/project"
    elif mutation == "artifact_id":
        provenance["artifact_id"] = 0
    elif mutation == "expired":
        artifact["artifact"]["expired"] = True
    elif mutation == "run_id":
        artifact["artifact"]["workflow_run"]["id"] = 8
    elif mutation == "event":
        artifact["run"]["event"] = "pull_request"
    elif mutation == "status":
        artifact["run"]["status"] = "in_progress"
    elif mutation == "conclusion":
        artifact["run"]["conclusion"] = "failure"
    elif mutation == "tested_commit":
        provenance["tested_commit"] = "0" * 40
    elif mutation == "attempt":
        provenance["attempt"] = 2
    elif mutation == "workflow_sha":
        provenance["workflow_sha"] = "0" * 40
    elif mutation == "workflow_path":
        artifact["run"]["path"] = ".github/workflows/unreviewed.yml"
    elif mutation == "workflow_content":
        endpoint = f"repos/{REPOSITORY}/contents/{WORKFLOW_PATH}?ref={artifact['trusted_ref']}"
        artifact["endpoints"][endpoint] = json.dumps(
            {"content": base64.b64encode(b"unreviewed workflow").decode()}
        ).encode()
    elif mutation == "provenance_digest":
        provenance["artifact_digest"] = "0" * 64
    elif mutation == "server_digest":
        artifact["artifact"]["digest"] = "sha256:" + "0" * 64
    else:
        provenance["manifest_hash"] = "0" * 64
    replace_response(artifact, "artifacts", artifact["artifact"])
    replace_response(artifact, "runs", artifact["run"])
    with pytest.raises(ValueError, match=message):
        verify(artifact)


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("manifest", "not present in verified artifact"),
        ("assertions", "report file differs"),
        ("completed", "completion marker mismatch"),
        ("duplicate", "duplicate artifact members"),
        ("prefix", "unsafe repository-relative path"),
    ],
)
def test_valid_download_digest_does_not_excuse_mismatched_or_ambiguous_members(
    artifact, mutation, message
):
    if mutation == "manifest":
        (artifact["directory"] / "manifest.json").write_bytes(b'{"changed":true}')
    elif mutation == "assertions":
        (artifact["directory"] / "assertions.jsonl").write_bytes(b"altered results")
    elif mutation == "completed":
        (artifact["directory"] / "COMPLETED").write_bytes(b"altered marker")
    elif mutation == "duplicate":
        replace_archive(
            artifact, list(artifact["files"].items()) + [("manifest.json", b"second manifest")]
        )
    else:
        artifact["entry"]["artifact_prefix"] = "../outside"
    with pytest.raises(ValueError, match=message):
        verify(artifact)


def test_missing_archive_member_and_malformed_json_cannot_pass(artifact):
    replace_archive(
        artifact, [item for item in artifact["files"].items() if item[0] != "assertions.jsonl"]
    )
    with pytest.raises(KeyError):
        verify(artifact)
    replace_archive(artifact, list(artifact["files"].items()))
    artifact["endpoints"][f"repos/{REPOSITORY}/actions/artifacts/42"] = b"not-json"
    with pytest.raises(json.JSONDecodeError):
        verify(artifact)


def test_unapproved_repository_identity_is_rejected_before_fetch(repository):
    trust = deepcopy(repository["trust"])
    trust["repository"] = "../../attacker"
    write_json(repository["root"] / "config/quality_trust.v1.json", trust)
    sha = commit_files(repository["root"], "malformed trust fixture")
    with pytest.raises(ValueError, match="invalid repository identity"):
        verify_github_artifacts(
            repository["root"],
            sha,
            [],
            getter=lambda endpoint: pytest.fail("must not fetch malformed repository"),
        )


def test_default_fetch_uses_gh_without_shell_and_preserves_git_verification(artifact, monkeypatch):
    original_run = subprocess.run
    gh_calls = []

    def local_run(args, **kwargs):
        if args[0] == "gh":
            assert args[:2] == ["gh", "api"]
            assert kwargs == {"check": True, "capture_output": True}
            gh_calls.append(args[2])
            return subprocess.CompletedProcess(args, 0, stdout=artifact["endpoints"][args[2]])
        return original_run(args, **kwargs)

    monkeypatch.setattr(quality_context.subprocess, "run", local_run)
    assert verify_github_artifacts(
        artifact["root"], artifact["trusted_ref"], [artifact["entry"]]
    ) == [artifact["entry"]["provenance"]]
    assert len(gh_calls) == 4


def test_stale_ancestor_cannot_reactivate_an_old_trust_policy(repository):
    root = repository["root"]
    old = repository["trusted_ref"]
    (root / "accepted-update.txt").write_text("next accepted version", encoding="utf-8")
    current = commit_files(root, "next accepted trust")
    git_at(root, "update-ref", "refs/remotes/origin/main", current)
    with pytest.raises(ValueError, match="current accepted"):
        load_trust_context(root, old)
