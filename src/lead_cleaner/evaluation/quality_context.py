"""Reproducibility fingerprints and trusted Git inputs for the quality CLI."""

import fnmatch
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from lead_cleaner.evaluation.quality_schema import content_hash


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, encoding="utf-8"
    ).stdout.strip()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path.name}")
    return value


def safe_relative(path: str) -> str:
    if not path or "\\" in path or path.startswith(("/", "-")) or ":" in path:
        raise ValueError("unsafe repository-relative path")
    if any(part in {"", ".", ".."} for part in path.split("/")):
        raise ValueError("unsafe repository-relative path")
    return path


def trusted_json(root: Path, trusted_ref: str, path: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", trusted_ref):
        raise ValueError("trusted reference must be an explicit full commit SHA")
    value = json.loads(git(root, "show", f"{trusted_ref}:{safe_relative(path)}"))
    if not isinstance(value, dict):
        raise ValueError("trusted JSON is not an object")
    return value


def verify_protected_files(root: Path, trusted_ref: str) -> dict[str, Any]:
    protocol = trusted_json(root, trusted_ref, "config/quality_baseline.v1.json")
    patterns = protocol["protected_patterns"]
    tracked = git(root, "ls-tree", "-r", "--name-only", trusted_ref).splitlines()
    old_files = {name for name in tracked if any(fnmatch.fnmatchcase(name, p) for p in patterns)}
    current = {
        p.relative_to(root).as_posix() for pat in patterns for p in root.glob(pat) if p.is_file()
    }
    differences = sorted(old_files ^ current)
    for name in sorted(old_files & current):
        expected = subprocess.run(
            ["git", "-C", str(root), "show", f"{trusted_ref}:{name}"],
            check=True,
            capture_output=True,
        ).stdout
        # Compare logical text across Git LF and Windows checkouts; retain byte hashes separately.
        if expected.replace(b"\r\n", b"\n") != (root / name).read_bytes().replace(b"\r\n", b"\n"):
            differences.append(name)
    if differences:
        raise ValueError(
            "quality protocol upgrade requires review: " + ", ".join(sorted(set(differences)))
        )
    return {"trusted_ref": trusted_ref, "verified_files": sorted(old_files)}


def _hash_files(root: Path, names: list[str]) -> str:
    return content_hash(
        {name: sha256_file(root / name) for name in sorted(names) if (root / name).is_file()}
    )


def build_metadata(
    root: Path, cases: list[dict[str, Any]], mode: str, protocol: dict[str, Any]
) -> dict[str, Any]:
    commit = git(root, "rev-parse", "HEAD")
    dirty = git(
        root,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        "src",
        "scripts",
        "config",
        "data/evals",
        "data/rag_eval",
        "data/knowledge_snapshot",
        "data/recommendation_eval",
        "pyproject.toml",
        "uv.lock",
        "requirements.txt",
        ".github",
    )
    dependencies = sorted(
        {
            (d.metadata["Name"].lower(), d.version)
            for d in importlib.metadata.distributions()
            if d.metadata["Name"]
        }
    )
    environment = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "system": platform.system(),
        "machine": platform.machine(),
        "dependencies": dependencies,
    }
    source_files = [p.relative_to(root).as_posix() for p in (root / "src").rglob("*.py")]
    evaluator_files = [
        name
        for name in source_files
        if "/evaluation/" in name
        or name.endswith(("rag/evaluation_report.py", "rag/eval_runner.py", "rag/eval_schemas.py"))
    ]
    loaded = {}
    project_root = root.resolve()
    source_root = (project_root / "src").resolve()
    if not source_root.is_relative_to(project_root):
        raise ValueError("project source directory escapes the requested repository")
    # Rebuild the inventory on every call: the CLI checks before execution and
    # again afterwards, including business modules imported lazily by an adapter.
    for name, module in list(sys.modules.items()):
        if name != "lead_cleaner" and not name.startswith("lead_cleaner."):
            continue
        filename = getattr(module, "__file__", None)
        if not isinstance(filename, str) or Path(filename).suffix != ".py":
            raise ValueError(f"loaded module has no verifiable Python source: {name}")
        location = Path(filename).resolve()
        module_path = source_root.joinpath(*name.split("."))
        expected = (
            module_path / "__init__.py"
            if hasattr(module, "__path__")
            else module_path.with_suffix(".py")
        ).resolve()
        if (
            not expected.is_relative_to(source_root)
            or location != expected
            or not expected.is_file()
        ):
            raise ValueError(f"loaded module source differs from requested repository: {name}")
        actual_hash = sha256_file(location)
        if actual_hash != sha256_file(expected):
            raise ValueError(f"loaded module source changed during verification: {name}")
        loaded[name] = {"path": str(location), "sha256": actual_hash}
    labels_reviewed = all(c.get("review_status") == "reviewed" for c in cases)
    return {
        "schema_version": "p0-quality.v1",
        "mode": mode,
        "tested_commit": commit,
        "s0_reference": protocol["s0_reference"],
        "provisional": bool(dirty) or not labels_reviewed,
        "source_dirty": bool(dirty),
        "business_labels_reviewed": labels_reviewed,
        "protocol_id": protocol["protocol_id"],
        "protocol_hash": content_hash(protocol),
        "rubric_hash": content_hash(
            {"version": protocol["rubric_version"], "evaluator": _hash_files(root, evaluator_files)}
        ),
        "evaluator_hash": _hash_files(root, evaluator_files),
        "code_hash": _hash_files(root, source_files),
        "suite_hash": content_hash(cases),
        "evaluation_data_hash": _hash_files(
            root, ["data/rag_eval/eval_queries.json", "data/recommendation_eval/golden_cases.json"]
        ),
        "knowledge_hash": _hash_files(
            root,
            [
                "data/knowledge_snapshot/knowledge_chunks.json",
                "data/knowledge_snapshot/translations.zh.json",
                "data/demo/lead_feature_fixtures.json",
            ],
        ),
        "environment_hash": content_hash(environment),
        "environment": environment,
        "dependency_files": {
            name: sha256_file(root / name) for name in ("uv.lock", "requirements.txt")
        },
        "loaded_modules": loaded,
        "app_mode": "rule_only",
        "live_status": "not_run" if mode != "live" else "requested",
        "product_release_status": "not_evaluated",
    }


def load_trust_context(root: Path, trusted_ref: str) -> dict[str, Any]:
    # The anchor is a fetched remote default branch, never the candidate's own report.
    if trusted_ref != git(root, "rev-parse", "refs/remotes/origin/main"):
        raise ValueError("trusted reference is not the current accepted target branch")
    value = trusted_json(root, trusted_ref, "config/quality_trust.v1.json")
    issues = trusted_json(root, trusted_ref, "config/quality_known_issues.v1.json")["issues"]
    return value | {"known_issues_hash": content_hash(issues), "verified_artifacts": []}


def verify_github_artifacts(
    root: Path,
    trusted_ref: str,
    entries: list[dict[str, Any]],
    *,
    getter: Any = None,
) -> list[dict[str, Any]]:
    """Bind local reports to downloaded immutable CI artifacts and a trusted workflow.

    Only push/dispatch runs of the exact candidate are accepted for release. PR
    merge-ref artifacts remain diagnostic and must be rerun on the final commit.
    """
    import io
    import zipfile

    def fetch(endpoint: str) -> bytes:
        if getter is not None:
            return getter(endpoint)
        return subprocess.run(["gh", "api", endpoint], check=True, capture_output=True).stdout

    trust = trusted_json(root, trusted_ref, "config/quality_trust.v1.json")
    repository = trust["repository"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository identity")
    verified = []
    for entry in entries:
        provenance = entry["provenance"]
        if provenance.get("repository") != repository:
            raise ValueError("artifact repository mismatch")
        artifact_id = int(provenance["artifact_id"])
        if artifact_id < 1:
            raise ValueError("invalid artifact id")
        artifact = json.loads(fetch(f"repos/{repository}/actions/artifacts/{artifact_id}"))
        run_id = int(provenance["run_id"])
        run = json.loads(fetch(f"repos/{repository}/actions/runs/{run_id}"))
        if artifact.get("expired") or artifact.get("workflow_run", {}).get("id") != run_id:
            raise ValueError("artifact expired or run mismatch")
        if run.get("event") not in {"push", "workflow_dispatch"}:
            raise ValueError("release requires an exact-commit push or dispatch run")
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            raise ValueError("artifact workflow did not complete successfully")
        if run.get("head_sha") != provenance["tested_commit"] or run.get("run_attempt") != int(
            provenance["attempt"]
        ):
            raise ValueError("artifact candidate or attempt mismatch")
        if provenance.get("workflow_sha") != run["head_sha"]:
            raise ValueError("workflow commit mismatch")
        workflow_path = run["path"].split("@", 1)[0]
        if workflow_path not in trust["approved_workflow_paths"]:
            raise ValueError("unapproved workflow path")
        expected_workflow = git(root, "show", f"{trusted_ref}:{safe_relative(workflow_path)}")
        import base64

        remote_file = json.loads(
            fetch(f"repos/{repository}/contents/{workflow_path}?ref={run['head_sha']}")
        )
        workflow = base64.b64decode(remote_file["content"], validate=False).decode("utf-8").strip()
        if workflow.replace("\r\n", "\n") != expected_workflow.replace("\r\n", "\n"):
            raise ValueError("workflow differs from accepted protocol")
        raw = fetch(f"repos/{repository}/actions/artifacts/{artifact_id}/zip")
        digest = hashlib.sha256(raw).hexdigest()
        expected_digest = str(provenance["artifact_digest"]).removeprefix("sha256:")
        if (
            digest != expected_digest
            or artifact.get("digest", "").removeprefix("sha256:") != digest
        ):
            raise ValueError("artifact digest mismatch")
        prefix = entry.get("artifact_prefix", "")
        if prefix:
            prefix = safe_relative(prefix) + "/"
        directory = Path(entry["directory"])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if len(set(archive.namelist())) != len(archive.namelist()):
                raise ValueError("duplicate artifact members")
            manifest_bytes = archive.read(prefix + "manifest.json")
            if manifest_bytes != (directory / "manifest.json").read_bytes():
                raise ValueError("local report not present in verified artifact")
            manifest = json.loads(manifest_bytes)
            # Every sealed file must be byte-for-byte present in the verified archive.
            for file in directory.iterdir():
                if file.is_file() and file.name != "COMPLETED":
                    if archive.read(prefix + file.name) != file.read_bytes():
                        raise ValueError("local report file differs from artifact")
            if archive.read(prefix + "COMPLETED") != (directory / "COMPLETED").read_bytes():
                raise ValueError("artifact completion marker mismatch")
            del manifest
        if hashlib.sha256(manifest_bytes).hexdigest() != provenance["manifest_hash"]:
            raise ValueError("provenance manifest mismatch")
        verified.append(provenance)
    return verified
