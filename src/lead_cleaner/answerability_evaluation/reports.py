"""Immutable P0-02 reports; raw observations are written before scoring."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .registry import protocol_spec

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
V2_BINDINGS = ("source_manifest_hash", "group_source_hash")
V2_GROUPS = {
    "handbook": {"case_count": 18, "turn_count": 28, "retrieval_units": 39},
    "synthetic_special": {"case_count": 6, "turn_count": 8, "retrieval_units": 15},
}
V2_SPECIAL_CASES = {"AB09", "AB10", "AB15", "AB16", "AB17", "AB23"}
V2_ASSERTIONS = {"execution", "facts_state", "answer_content", "grounding", "clarification"}
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


def fingerprint_fields(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    return FINGERPRINTS + (V2_BINDINGS if metadata.get("protocol_id") == "p0-02.v2" else ())


def group_binding(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: metadata.get(field)
        for field in ("evaluation_groups", "case_groups", "case_sources", "source_manifest_hash")
    }


def _grouped_metrics(value: Any) -> None:
    if not isinstance(value, dict):
        raise ReportError("Invalid grouped metrics")
    if value.get("applicability") == "not_observed":
        if value != {"applicability": "not_observed", "value": None}:
            raise ReportError("Invalid unobserved metric")
    elif "applicability" in value:
        _metric(value)
    else:
        for child in value.values():
            if isinstance(child, dict):
                _grouped_metrics(child)


def _validate_v2(data: Mapping[str, Any]) -> None:
    from .metrics import summarize_retrieval

    metadata = data["metadata"]
    groups = metadata.get("evaluation_groups")
    mapping = metadata.get("case_groups")
    sources = metadata.get("case_sources")
    wanted = {
        f"AB{i:02d}": "synthetic_special" if f"AB{i:02d}" in V2_SPECIAL_CASES else "handbook"
        for i in range(1, 25)
    }
    if groups != V2_GROUPS or mapping != wanted:
        raise ReportError("V2 requires the frozen per-group case/turn/retrieval cohorts")
    if (
        not isinstance(sources, dict)
        or set(sources) != set(wanted)
        or any(
            not isinstance(source, dict)
            or set(source) != {"scenario_origin", "corpus_origin", "snapshot_id"}
            or any(not isinstance(v, str) or not v for v in source.values())
            for source in sources.values()
        )
    ):
        raise ReportError("V2 case source coverage is incomplete")
    if not isinstance(metadata.get("source_manifest"), dict) or not metadata["source_manifest"]:
        raise ReportError("V2 requires the complete source manifest")
    if metadata["source_manifest"].get("schema_version") != "answerability-source-manifest.v2":
        raise ReportError("Source manifest version differs")
    if any(
        source["scenario_origin"] != "synthetic_question"
        or source["corpus_origin"]
        != ("original_handbook" if wanted[case_id] == "handbook" else "synthetic_fixture")
        for case_id, source in sources.items()
    ):
        raise ReportError("V2 case source category differs from its fixed group")
    if metadata.get("source_manifest_hash") != content_hash(metadata["source_manifest"]):
        raise ReportError("Source manifest binding mismatch")
    if metadata.get("group_source_hash") != content_hash(group_binding(metadata)):
        raise ReportError("Group/source binding mismatch")
    by_case: dict[str, list[dict[str, Any]]] = {}
    for observation in data["observations"]:
        by_case.setdefault(observation["case_id"], []).append(observation)
        if any(
            field in observation
            for field in ("evaluation_group", "scenario_origin", "corpus_origin")
        ):
            raise ReportError("Scoring-side source labels cannot enter raw observations")
    if set(by_case) != set(wanted):
        raise ReportError("V2 observation case coverage differs")
    for case_id, observations in by_case.items():
        expected_turns = ["T1", "T2", "T3"] if int(case_id[2:]) >= 19 else ["T1"]
        if [o["turn_id"] for o in observations] != expected_turns:
            raise ReportError("V2 frozen turn coverage differs")
        for observation in observations:
            rows = [
                r
                for r in data["assertions"]
                if key(r, OBSERVATION_FIELDS) == key(observation, OBSERVATION_FIELDS)
            ]
            if {r["assertion_id"] for r in rows} != V2_ASSERTIONS or any(
                r["probe_id"] != "conversation"
                or r["trial_id"] != "1"
                or r.get("mandatory") is not True
                for r in rows
            ):
                raise ReportError("V2 requires every fixed mandatory turn assertion")
    metrics = data["metrics"]
    if (
        not isinstance(metrics, dict)
        or set(metrics.get("groups", {})) != set(V2_GROUPS)
        or metrics.get("cross_group_accuracy") != "not_computed"
        or "replies" in metrics
        or "retrieval" in metrics
        or metrics.get("retrieval_applicability")
        != ("applicable" if metadata["mode"] == "rule_only" else "not_applicable")
    ):
        raise ReportError("V2 metrics must keep source groups separate")
    for name, planned in V2_GROUPS.items():
        cases = {case_id for case_id, group in wanted.items() if group == name}
        observed = [o for o in data["observations"] if o["case_id"] in cases]
        retrieval = [r for r in data["retrieval"] if r["case_id"] in cases]
        if any(r.get("protocol_id") != "p0-02.v2" or r.get("turn_id") != "T1" for r in retrieval):
            raise ReportError("V2 retrieval protocol/turn binding differs")
        expected_retrieval = planned["retrieval_units"] if metadata["mode"] == "rule_only" else 0
        if len(observed) != planned["turn_count"] or len(retrieval) != expected_retrieval:
            raise ReportError("V2 group execution coverage differs")
        if metadata["mode"] == "rule_only":
            singles = {case_id for case_id in cases if int(case_id[2:]) < 19}
            paths = {r["path"] for r in retrieval}
            if paths != {"raw_query", "runtime_rule_query", "runtime_fused_query"} or {
                (r["case_id"], r["path"]) for r in retrieval
            } != {(case_id, path) for case_id in singles for path in paths}:
                raise ReportError("V2 retrieval requires all three paths for each single-turn case")
        group = metrics["groups"][name]
        expected_counts = {
            "case_count": planned["case_count"],
            "turn_count": planned["turn_count"],
            "retrieval_units": expected_retrieval,
            "observed_turn_count": len(observed),
            "observed_retrieval_units": len(retrieval),
        }
        if (
            not isinstance(group, dict)
            or group.get("counts") != expected_counts
            or any(not isinstance(group.get(field), dict) for field in ("replies", "retrieval"))
        ):
            raise ReportError("V2 grouped metric denominators/coverage differ")
        for metric_name, denominator in (
            ("all", planned["turn_count"]),
            ("conversation_success", planned["case_count"]),
            ("adjudication_coverage", planned["turn_count"]),
            ("answer_coverage", planned["turn_count"]),
        ):
            metric = group["replies"].get(metric_name, {})
            if (
                metric.get("denominator") != denominator
                or metric.get("planned_count") != denominator
            ):
                raise ReportError("V2 reply metric shrank its fixed planned denominator")
        # Every mutually exclusive cohort must retain all turns, including
        # failures/unknowns. Exact per-label membership is checked with the
        # independently loaded dataset at the gate boundary.
        for prefix, labels in (
            ("state:", ("answerable", "partial", "unanswerable")),
            ("language:", ("zh", "en", "mixed")),
            ("turns:", ("single", "multi")),
        ):
            cohort_keys = {prefix + label for label in labels}
            actual_keys = {field for field in group["replies"] if field.startswith(prefix)}
            # The existing aggregator omits languages with zero samples (the
            # special cohort has no mixed-language cases). Never omit a
            # positive cohort: its denominator must still sum to all turns.
            if (
                not actual_keys
                or not actual_keys <= cohort_keys
                or (prefix != "language:" and actual_keys != cohort_keys)
            ):
                raise ReportError("V2 reply cohort labels are incomplete or unexpected")
            cohort = [group["replies"][field] for field in sorted(actual_keys)]
            if (
                any(
                    not isinstance(metric, dict)
                    or type(metric.get("denominator")) is not int
                    or metric["denominator"] < 0
                    or metric.get("planned_count") != metric["denominator"]
                    for metric in cohort
                )
                or sum(metric["denominator"] for metric in cohort) != planned["turn_count"]
            ):
                raise ReportError("V2 reply cohort shrank its fixed planned denominator")
        try:
            recomputed_retrieval = summarize_retrieval(retrieval)
        except (KeyError, TypeError, ValueError) as exc:
            raise ReportError("V2 retrieval metric coverage is incomplete") from exc
        if canonical_json(group["retrieval"]) != canonical_json(recomputed_retrieval):
            raise ReportError("V2 grouped retrieval differs from its raw metric records")
        _grouped_metrics(group["replies"])
        _grouped_metrics(group["retrieval"])


def validate_run(
    data: Mapping[str, Any],
    expected_keys: Iterable[Any] | None = None,
    expected_retrieval_keys: Iterable[Any] | None = None,
) -> None:
    metadata = data["metadata"]
    try:
        spec = protocol_spec(metadata.get("protocol_id", ""))
    except ValueError as exc:
        raise ReportError("Unsupported answerability protocol") from exc
    if metadata.get("schema_version") != spec["schema_version"]:
        raise ReportError("Unsupported answerability protocol")
    if metadata.get("mode") not in {"rule_only", "mocked_model"} or any(
        not metadata.get(field) for field in fingerprint_fields(metadata)
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
    if metadata["protocol_id"] == "p0-02.v2":
        _validate_v2(data)
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
        "storage_version": "answerability-run."
        + run_data["metadata"]["protocol_id"].rsplit(".", 1)[1],
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
            manifest.get("storage_version") not in {"answerability-run.v1", "answerability-run.v2"}
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
        if (
            manifest["storage_version"]
            != "answerability-run." + data["metadata"]["protocol_id"].rsplit(".", 1)[1]
        ):
            raise ReportError("Storage and protocol versions differ")
        return data | {
            "directory": str(directory.resolve()),
            "manifest_hash": digest,
            "manifest": manifest,
        }
    except (OSError, UnicodeError, KeyError, TypeError, AttributeError) as exc:
        raise ReportError("Malformed or incomplete answerability report") from exc
