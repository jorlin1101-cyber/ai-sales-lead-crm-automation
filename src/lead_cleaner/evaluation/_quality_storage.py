"""Immutable, content-checked storage for quality-evaluation records."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from .quality_schema import KEY_FIELDS, content_hash

AssertionKey = tuple[str, ...]
_STORAGE_VERSION = "quality-run-v1"
_CORE_FILES = {"observations.jsonl", "assertions.jsonl", "summary.md"}


class QualityReportError(ValueError):
    """An artifact is incomplete, invalid, or cannot be trusted."""


def json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def object_hash(value: Any) -> str:
    return content_hash(value)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assertion_key(value: Mapping[str, Any] | Iterable[str]) -> AssertionKey:
    parts = (
        tuple(value.get(field) for field in KEY_FIELDS)
        if isinstance(value, Mapping)
        else tuple(value)
    )
    if len(parts) != len(KEY_FIELDS) or any(
        not isinstance(part, str) or not part for part in parts
    ):
        raise QualityReportError("An assertion key requires six non-empty string identifiers.")
    return cast(AssertionKey, parts)


def key_set(values: Iterable[Mapping[str, Any] | Iterable[str]]) -> set[AssertionKey]:
    result: set[AssertionKey] = set()
    for value in values:
        key = assertion_key(value)
        if key in result:
            raise QualityReportError(f"Duplicate assertion key: {key!r}")
        result.add(key)
    return result


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualityReportError(f"Duplicate JSON member: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualityReportError(
            f"Cannot read JSON artifact {path.name}: {type(exc).__name__}"
        ) from exc


def _read_lines(path: Path) -> list[dict[str, Any]]:
    try:
        items = [
            json.loads(line, object_pairs_hook=_pairs)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualityReportError(f"Cannot read JSONL artifact {path.name}") from exc
    if any(not isinstance(item, dict) for item in items):
        raise QualityReportError("JSONL rows must be objects.")
    return items


def _write_new(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def write_record(path: Path, record: Mapping[str, Any]) -> Path:
    """Append one record; an existing record, including a partial one, is never replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_new(path, json_bytes(record))
    return path


def _checked_file(root: Path, name: str) -> Path:
    if (
        not isinstance(name, str)
        or not name
        or Path(name).name != name
        or "/" in name
        or "\\" in name
    ):
        raise QualityReportError("Manifest file names must be plain relative file names.")
    path = root / name
    if path.is_symlink() or path.resolve().parent != root.resolve() or not path.is_file():
        raise QualityReportError(f"Missing or unsafe report file: {name}")
    return path


def _validate_rows(rows: list[dict[str, Any]], expected: set[AssertionKey], mode: str) -> None:
    if key_set(rows) != expected:
        raise QualityReportError("Assertion coverage differs from the frozen expected-key set.")
    for row in rows:
        if row["mode"] != mode:
            raise QualityReportError("Assertion mode differs from the run mode.")
        execution, behavior = row.get("execution_status"), row.get("behavior_status")
        if execution not in {"completed", "error", "not_run", "not_applicable"}:
            raise QualityReportError("Invalid assertion execution status.")
        if execution == "completed" and behavior not in {"pass", "fail", "needs_review"}:
            raise QualityReportError("A completed assertion requires a behavior verdict.")
        if execution != "completed" and behavior is not None:
            raise QualityReportError("An unexecuted assertion cannot carry a behavior verdict.")
        if execution == "not_applicable":
            raise QualityReportError(
                "An applicable expected assertion cannot be made not_applicable."
            )
        if row.get("manual_review") is not True and behavior == "needs_review":
            raise QualityReportError("Only manual-review assertions may need review.")


def seal_run(
    output_dir: str | Path,
    run_data: dict[str, Any],
    *,
    expected_keys: Iterable[Mapping[str, Any] | Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Seal a complete result set. Failures remain failures; missing results are not invented."""
    metadata = dict(run_data["metadata"])
    expected = key_set(expected_keys if expected_keys is not None else metadata["expected_keys"])
    if not expected:
        raise QualityReportError("A formal run must have at least one applicable assertion.")
    if key_set(metadata["expected_keys"]) != expected:
        raise QualityReportError("Metadata and external expected-key sets differ.")
    rows = list(run_data["assertions"])
    _validate_rows(rows, expected, metadata["mode"])
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    files: dict[str, dict[str, Any]] = {}
    summary = run_data.get(
        "summary",
        "Quality evaluation: "
        + str(metadata["run_id"])
        + "\n\nThis sealed record is not a release approval.\n",
    )
    if not isinstance(summary, str):
        raise QualityReportError("Run summary must be text.")
    payloads: dict[str, bytes] = {
        "observations.jsonl": b"".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
            + b"\n"
            for row in run_data.get("observations", [])
        ),
        "assertions.jsonl": b"".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
            + b"\n"
            for row in rows
        ),
        "summary.md": summary.encode("utf-8"),
    }
    for name, value in run_data.get("subreports", {}).items():
        if (
            not isinstance(name, str)
            or not name
            or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in name)
        ):
            raise QualityReportError("Invalid subreport name.")
        payloads[name + ".json"] = json_bytes(value)
    for name, content in payloads.items():
        _write_new(output / name, content)
        files[name] = {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
    manifest = {
        "schema_version": _STORAGE_VERSION,
        "state": "sealed",
        "metadata": metadata,
        "files": files,
        "subreport_names": sorted(run_data.get("subreports", {})),
    }
    temporary = output / "manifest.json.tmp"
    _write_new(temporary, json_bytes(manifest))
    temporary.replace(output / "manifest.json")
    _write_new(
        output / "COMPLETED", json_bytes({"manifest_sha256": file_hash(output / "manifest.json")})
    )
    return load_run(output, expected_keys=expected)


def load_run(
    output_dir: str | Path,
    *,
    expected_keys: Iterable[Mapping[str, Any] | Iterable[str]] | None = None,
) -> dict[str, Any]:
    root = Path(output_dir)
    manifest_path = _checked_file(root, "manifest.json")
    completion = read_json(_checked_file(root, "COMPLETED"))
    digest = file_hash(manifest_path)
    if not isinstance(completion, dict) or completion.get("manifest_sha256") != digest:
        raise QualityReportError("Completion marker does not match the manifest.")
    manifest = read_json(manifest_path)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != _STORAGE_VERSION
        or manifest.get("state") != "sealed"
    ):
        raise QualityReportError("Invalid sealed-run manifest.")
    metadata, files = manifest.get("metadata"), manifest.get("files")
    names = manifest.get("subreport_names")
    if (
        not isinstance(metadata, dict)
        or not isinstance(files, dict)
        or not isinstance(names, list)
        or any(not isinstance(name, str) for name in names)
    ):
        raise QualityReportError("Invalid manifest metadata or file index.")
    required = _CORE_FILES | {name + ".json" for name in names}
    if len(names) != len(set(names)) or set(files) != required:
        raise QualityReportError("Manifest file set is invalid.")
    if {path.name for path in root.iterdir()} != required | {"manifest.json", "COMPLETED"}:
        raise QualityReportError("Report directory contains missing or unexpected files.")
    for name, specification in files.items():
        path = _checked_file(root, name)
        if (
            not isinstance(specification, dict)
            or specification.get("size") != path.stat().st_size
            or specification.get("sha256") != file_hash(path)
        ):
            raise QualityReportError(f"Report content integrity failed: {name}")
    expected = key_set(metadata.get("expected_keys", []))
    if not expected or expected_keys is not None and expected != key_set(expected_keys):
        raise QualityReportError("Expected-key set does not match the trusted protocol.")
    assertions = _read_lines(root / "assertions.jsonl")
    observations = _read_lines(root / "observations.jsonl")
    _validate_rows(assertions, expected, metadata.get("mode", ""))
    observed_hashes = {object_hash(row): row for row in observations}
    for row in assertions:
        digest_value = row.get("observation_hash")
        if digest_value is not None and digest_value not in observed_hashes:
            raise QualityReportError("Assertion observation hash has no sealed observation.")
        if digest_value is not None and any(
            row[field] != observed_hashes[digest_value].get(field)
            for field in KEY_FIELDS
            if field != "assertion_id"
        ):
            raise QualityReportError(
                "Assertion observation belongs to a different checkpoint or trial."
            )
        if row["execution_status"] == "completed" and digest_value is None:
            raise QualityReportError("Completed assertions require sealed observations.")
    return {
        "metadata": metadata,
        "observations": observations,
        "assertions": assertions,
        "subreports": {name: read_json(root / (name + ".json")) for name in names},
        "manifest_hash": digest,
        "directory": str(root.resolve()),
    }
