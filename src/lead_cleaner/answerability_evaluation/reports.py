"""Immutable P0-02 reports; raw observations are written before scoring."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

KEY_FIELDS = ("protocol_id", "mode", "case_id", "probe_id", "turn_id", "assertion_id", "trial_id")
OBSERVATION_FIELDS = tuple(field for field in KEY_FIELDS if field != "assertion_id")
METRICS = (
    "supported_facet_hit",
    "support_completion_rr",
    "answerable_facet_recall",
    "ndcg",
    "unjudged_rate",
)
FINGERPRINTS = (
    "protocol_id",
    "mode",
    "protocol_hash",
    "dataset_hash",
    "knowledge_hash",
    "evaluator_hash",
    "environment_hash",
)
CORE_FILES = {
    "metadata.json",
    "observations.jsonl",
    "assertions.jsonl",
    "retrieval.json",
    "metrics.json",
    "summary.md",
    "OBSERVATIONS",
}


class ReportError(ValueError):
    """An incomplete, modified, incompatible, or untrusted evaluation record."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReportError("Duplicate JSON member")
        result[key] = value
    return result


def parse_json(text: str) -> Any:
    def invalid(value: str) -> Any:
        raise ReportError("Nonfinite JSON value: " + value)

    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReportError("Invalid JSON artifact") from exc


def read_json(path: str | Path) -> Any:
    try:
        return parse_json(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReportError("Missing JSON artifact") from exc


def write_bytes(path: Path, value: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def write_record(path: str | Path, value: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_bytes(target, canonical_json(value) + b"\n")
    return target


def key(
    value: Mapping[str, Any] | Iterable[str], fields: tuple[str, ...] = KEY_FIELDS
) -> tuple[str, ...]:
    parts = (
        tuple(value.get(field) for field in fields) if isinstance(value, Mapping) else tuple(value)
    )
    if len(parts) != len(fields) or any(not isinstance(part, str) or not part for part in parts):
        raise ReportError("Invalid evaluation identity")
    return parts  # type: ignore[return-value]


def keys(values: Iterable[Any], fields: tuple[str, ...] = KEY_FIELDS) -> list[tuple[str, ...]]:
    result = [key(value, fields) for value in values]
    if len(set(result)) != len(result):
        raise ReportError("Duplicate evaluation identity")
    return result


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical_json(row) + b"\n" for row in rows)


def stage_observations(output: str | Path, observations: list[dict[str, Any]]) -> Path:
    """Create a new incomplete directory before invoking the independent scorer."""
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=False)
    raw = _jsonl(observations)
    write_bytes(directory / "observations.jsonl", raw)
    write_bytes(directory / "OBSERVATIONS", hashlib.sha256(raw).hexdigest().encode("ascii"))
    return directory


def _metric(metric: Any) -> None:
    if not isinstance(metric, dict) or metric.get("applicability") not in {
        "applicable",
        "not_applicable",
        "incomplete_judgments",
    }:
        raise ReportError("Invalid metric applicability")
    value = metric.get("value")
    if metric["applicability"] == "applicable":
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ReportError("Invalid applicable metric value")
    elif value is not None:
        raise ReportError("Unknown or inapplicable metric must be null")
    for field in ("numerator", "denominator"):
        number = metric.get(field)
        if number is not None and (
            type(number) not in {int, float} or not math.isfinite(number) or number < 0
        ):
            raise ReportError("Invalid metric count")
    for field in (
        "error_count",
        "not_run_count",
        "needs_review_count",
        "planned_count",
        "adjudicated_count",
        "excluded_by_design",
    ):
        if field in metric and (type(metric[field]) is not int or metric[field] < 0):
            raise ReportError("Invalid metric coverage count")


def validate_run(
    data: Mapping[str, Any],
    expected_keys: Iterable[Any] | None = None,
    expected_retrieval_keys: Iterable[Any] | None = None,
) -> None:
    metadata = data["metadata"]
    if (
        metadata.get("schema_version") != "answerability-eval.v1"
        or metadata.get("protocol_id") != "p0-02.v1"
    ):
        raise ReportError("Unsupported answerability protocol")
    if metadata.get("mode") not in {"rule_only", "mocked_model"} or any(
        not metadata.get(field) for field in FINGERPRINTS
    ):
        raise ReportError("Missing fingerprint or invalid mode")
    if metadata.get("real_model_calls") != 0:
        raise ReportError("Offline protocol cannot contain real model calls")
    expected = keys(metadata["expected_keys"])
    if not expected or expected_keys is not None and expected != keys(expected_keys):
        raise ReportError("Expected assertions differ from trusted suite")
    assertions = data["assertions"]
    if keys(assertions) != expected:
        raise ReportError("Assertion coverage or ordering differs")
    observation_keys = keys(data["observations"], OBSERVATION_FIELDS)
    wanted = list(dict.fromkeys(key(row, OBSERVATION_FIELDS) for row in assertions))
    if observation_keys != wanted:
        raise ReportError("Observation coverage or ordering differs")
    observed = {key(row, OBSERVATION_FIELDS): content_hash(row) for row in data["observations"]}
    for row in assertions:
        if row["mode"] != metadata["mode"] or row["protocol_id"] != metadata["protocol_id"]:
            raise ReportError("Assertion protocol or mode mismatch")
        execution, behavior = row.get("execution_status"), row.get("behavior_status")
        if (
            execution not in {"completed", "error", "not_run"}
            or (execution == "completed" and behavior not in {"pass", "fail", "needs_review"})
            or (execution != "completed" and behavior is not None)
        ):
            raise ReportError("Invalid execution/behavior states")
        if row.get("severity") not in {"critical", "major", "minor"}:
            raise ReportError("Invalid assertion severity")
        if behavior == "needs_review" and row.get("manual_review") is not True:
            raise ReportError("Unreviewable assertion cannot need review")
        if behavior == "fail" and not row.get("failure_type"):
            raise ReportError("Failure has no exact signature")
        if row.get("observation_hash") != observed[key(row, OBSERVATION_FIELDS)]:
            raise ReportError("Assertion is not bound to its raw observation")
    expected_retrieval = keys(metadata["expected_retrieval_keys"], ("case_id", "path"))
    if expected_retrieval_keys is not None and expected_retrieval != keys(
        expected_retrieval_keys, ("case_id", "path")
    ):
        raise ReportError("Retrieval keys differ from trusted suite")
    if (metadata["mode"] == "rule_only") != bool(expected_retrieval):
        raise ReportError("Retrieval applicability differs from offline protocol")
    if keys(data["retrieval"], ("case_id", "path")) != expected_retrieval:
        raise ReportError("Retrieval coverage or ordering differs")
    for row in data["retrieval"]:
        if row.get("execution_status") not in {"completed", "error", "not_run"} or set(
            row.get("metrics", {})
        ) != set(METRICS):
            raise ReportError("Invalid retrieval execution or missing metrics")
        for metric in row["metrics"].values():
            _metric(metric)
    canonical_json(data)


def seal_run(
    output: str | Path,
    run_data: Mapping[str, Any],
    *,
    expected_keys: Iterable[Any] | None = None,
    expected_retrieval_keys: Iterable[Any] | None = None,
) -> dict[str, Any]:
    validate_run(run_data, expected_keys, expected_retrieval_keys)
    directory = Path(output)
    if not directory.exists():
        stage_observations(directory, run_data["observations"])
    if directory.is_symlink() or {p.name for p in directory.iterdir()} != {
        "observations.jsonl",
        "OBSERVATIONS",
    }:
        raise ReportError("Output exists or contains an interrupted seal")
    raw = _jsonl(run_data["observations"])
    if (directory / "observations.jsonl").read_bytes() != raw or (
        directory / "OBSERVATIONS"
    ).read_text("ascii") != hashlib.sha256(raw).hexdigest():
        raise ReportError("Staged observations changed before scoring")
    for name in ("metadata", "retrieval", "metrics"):
        write_record(directory / (name + ".json"), run_data[name])
    write_bytes(directory / "assertions.jsonl", _jsonl(run_data["assertions"]))
    write_bytes(
        directory / "summary.md",
        str(run_data.get("summary", "P0-02：原始报告已封存；真实模型未测。\n")).encode("utf-8"),
    )
    manifest = {
        "storage_version": "answerability-run.v1",
        "files": {
            name: {"sha256": file_hash(directory / name), "size": (directory / name).stat().st_size}
            for name in sorted(CORE_FILES)
        },
    }
    write_record(directory / "manifest.json", manifest)
    write_bytes(directory / "COMPLETED", file_hash(directory / "manifest.json").encode("ascii"))
    return load_run(
        directory, expected_keys=expected_keys, expected_retrieval_keys=expected_retrieval_keys
    )


def load_run(
    path: str | Path,
    *,
    expected_keys: Iterable[Any] | None = None,
    expected_retrieval_keys: Iterable[Any] | None = None,
) -> dict[str, Any]:
    directory = Path(path)
    try:
        if directory.is_symlink() or {p.name for p in directory.iterdir()} != CORE_FILES | {
            "manifest.json",
            "COMPLETED",
        }:
            raise ReportError("Incomplete or unexpected report file set")
        if any(p.is_symlink() or not p.is_file() for p in directory.iterdir()):
            raise ReportError("Unsafe report member")
        manifest = read_json(directory / "manifest.json")
        if (
            manifest.get("storage_version") != "answerability-run.v1"
            or set(manifest.get("files", {})) != CORE_FILES
        ):
            raise ReportError("Unsupported or invalid report manifest")
        digest = file_hash(directory / "manifest.json")
        if (directory / "COMPLETED").read_text("ascii") != digest:
            raise ReportError("Completion marker does not bind the manifest")
        for name, entry in manifest["files"].items():
            if entry != {
                "sha256": file_hash(directory / name),
                "size": (directory / name).stat().st_size,
            }:
                raise ReportError("Sealed report bytes changed")
        data = {
            name: read_json(directory / (name + ".json"))
            for name in ("metadata", "retrieval", "metrics")
        }
        for name in ("observations", "assertions"):
            data[name] = [
                parse_json(line)
                for line in (directory / (name + ".jsonl")).read_text("utf-8").splitlines()
            ]
        if (directory / "OBSERVATIONS").read_text("ascii") != file_hash(
            directory / "observations.jsonl"
        ):
            raise ReportError("Observation-stage digest mismatch")
        validate_run(data, expected_keys, expected_retrieval_keys)
        return data | {
            "directory": str(directory.resolve()),
            "manifest_hash": digest,
            "manifest": manifest,
        }
    except (OSError, UnicodeError, KeyError, TypeError, AttributeError) as exc:
        raise ReportError("Malformed or incomplete answerability report") from exc
