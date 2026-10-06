"""Provider-verified artifact provenance, scoped exclusively to P0-02."""

from __future__ import annotations

import base64
import hashlib
import io
import re
import subprocess
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .registry import protocol_spec
from .reports import V2_BINDINGS, ReportError, load_run, parse_json
from .trust import git, require_protocol_trust, safe_relative, trusted_json

PROVENANCE_FIELDS = (
    "repository",
    "tested_commit",
    "workflow_sha",
    "run_id",
    "attempt",
    "artifact_id",
    "artifact_digest",
    "manifest_hash",
)


def verify_github_artifacts(
    root: Path,
    trusted_ref: str,
    entries: list[dict[str, Any]],
    *,
    getter: Callable[[str], bytes] | None = None,
    protocol_id: str = "p0-02.v1",
) -> list[dict[str, Any]]:
    spec = protocol_spec(protocol_id)
    trust = trusted_json(root, trusted_ref, spec["trust_path"])
    if trust.get("protocol_id") != protocol_id:
        raise ReportError("Artifact trust uses a different protocol")
    repository = trust.get("repository", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ReportError("Invalid repository")

    def fetch(endpoint: str) -> bytes:
        return (
            getter(endpoint)
            if getter
            else subprocess.run(["gh", "api", endpoint], check=True, capture_output=True).stdout
        )

    verified = []
    seen = set()
    for entry in entries:
        provenance = entry["provenance"]
        if (
            any(provenance.get(field) in (None, "") for field in PROVENANCE_FIELDS)
            or provenance["repository"] != repository
        ):
            raise ReportError("Incomplete or wrong-repository provenance")
        run = load_run(entry["directory"])
        if run["metadata"]["protocol_id"] != protocol_id:
            raise ReportError("Artifact report belongs to a different protocol")
        if protocol_id == "p0-02.v2" and any(
            field in provenance and provenance[field] != run["metadata"][field]
            for field in ("protocol_id", *V2_BINDINGS)
        ):
            raise ReportError("Artifact source/group binding mismatch")
        if (
            provenance["manifest_hash"] in seen
            or run["manifest_hash"] != provenance["manifest_hash"]
            or run["metadata"]["tested_commit"] != provenance["tested_commit"]
        ):
            raise ReportError("Duplicate or mismatched artifact report")
        seen.add(provenance["manifest_hash"])
        artifact_id, run_id = int(provenance["artifact_id"]), int(provenance["run_id"])
        if min(artifact_id, run_id, int(provenance["attempt"])) < 1:
            raise ReportError("Invalid artifact/run/attempt ID")
        artifact = parse_json(
            fetch(f"repos/{repository}/actions/artifacts/{artifact_id}").decode("utf-8")
        )
        workflow_run = parse_json(
            fetch(f"repos/{repository}/actions/runs/{run_id}").decode("utf-8")
        )
        if artifact.get("expired") or artifact.get("workflow_run", {}).get("id") != run_id:
            raise ReportError("Expired or mismatched artifact run")
        if (
            workflow_run.get("event") not in {"push", "workflow_dispatch"}
            or workflow_run.get("status") != "completed"
            or workflow_run.get("conclusion") != "success"
        ):
            raise ReportError("Formal evidence requires a successful exact-commit push/dispatch")
        if (
            workflow_run.get("head_sha") != provenance["tested_commit"]
            or workflow_run.get("run_attempt") != int(provenance["attempt"])
            or provenance["workflow_sha"] != workflow_run["head_sha"]
        ):
            raise ReportError("Artifact SHA or attempt mismatch")
        workflow_path = workflow_run["path"].split("@", 1)[0]
        if workflow_path not in trust.get("approved_workflow_paths", []):
            raise ReportError("Unapproved workflow")
        expected = git(root, "show", trusted_ref + ":" + safe_relative(workflow_path))
        remote = parse_json(
            fetch(
                f"repos/{repository}/contents/{workflow_path}?ref={workflow_run['head_sha']}"
            ).decode("utf-8")
        )
        actual = base64.b64decode(remote["content"]).decode("utf-8").strip()
        if expected.replace("\r\n", "\n") != actual.replace("\r\n", "\n"):
            raise ReportError("Workflow differs from approved source")
        raw = fetch(f"repos/{repository}/actions/artifacts/{artifact_id}/zip")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != str(provenance["artifact_digest"]).removeprefix(
            "sha256:"
        ) or digest != artifact.get("digest", "").removeprefix("sha256:"):
            raise ReportError("Artifact ZIP digest mismatch")
        prefix = entry.get("artifact_prefix", "")
        prefix = safe_relative(prefix) + "/" if prefix else ""
        directory = Path(run["directory"])
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)) or any(
                    name.startswith("/") or "\\" in name or ".." in name.split("/")
                    for name in names
                ):
                    raise ReportError("Unsafe or duplicate ZIP members")
                actual_members = {
                    name[len(prefix) :]
                    for name in names
                    if name.startswith(prefix) and not name.endswith("/")
                }
                expected_members = {p.name for p in directory.iterdir()}
                if actual_members != expected_members:
                    raise ReportError("Artifact report file set differs")
                for name in expected_members:
                    if archive.read(prefix + name) != (directory / name).read_bytes():
                        raise ReportError("Artifact report bytes differ")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise ReportError("Invalid artifact ZIP") from exc
        receipt = {field: provenance[field] for field in PROVENANCE_FIELDS}
        if protocol_id == "p0-02.v2":
            receipt.update(
                {field: run["metadata"][field] for field in ("protocol_id", *V2_BINDINGS)}
            )
        verified.append(receipt)
    return verified


def require_verified_artifact(
    run: Mapping[str, Any], trust_context: Mapping[str, Any]
) -> dict[str, Any]:
    require_protocol_trust(run["metadata"], trust_context, required=True)
    matches = [
        p
        for p in trust_context.get("verified_artifacts", [])
        if p.get("manifest_hash") == run["manifest_hash"]
    ]
    if (
        len(matches) != 1
        or any(matches[0].get(field) in (None, "") for field in PROVENANCE_FIELDS)
        or matches[0]["tested_commit"] != run["metadata"]["tested_commit"]
        or run["metadata"]["protocol_id"] == "p0-02.v2"
        and any(
            matches[0].get(field) != run["metadata"][field]
            for field in ("protocol_id", *V2_BINDINGS)
        )
    ):
        raise ReportError(
            "Formal acceptance requires independently provider-verified artifact bytes"
        )
    return dict(matches[0])
