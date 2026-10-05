"""Run the unchanged P0-01 CLI and compare local compatibility evidence.

This bridge does not accept a baseline or claim the formal cross-environment
regression gate passed. Its output separates frozen inputs from observed scores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lead_cleaner.evaluation.quality_report import load_run

MODES = ("rule_only", "mocked_model")
PATHS = ("raw_query", "runtime_rule_query", "runtime_fused_query")
KEY_FIELDS = ("mode", "case_id", "probe_id", "checkpoint", "assertion_id", "trial_id")
OUTCOME_FIELDS = (
    "execution_status",
    "behavior_status",
    "failure_type",
    "severity",
    "known_issue_id",
)
CONTRACT_FIELDS = (
    "mode",
    "protocol_id",
    "protocol_hash",
    "suite_hash",
    "cases_sha256",
    "effective_settings",
    "runner_version",
    "adapter_version",
)
RAW_FINGERPRINT_FIELDS = (
    "evaluator_hash",
    "knowledge_hash",
    "evaluation_data_hash",
    "dependency_files",
    "rubric_hash",
)


class CompatibilityError(ValueError):
    """Incomplete evidence cannot establish compatibility."""


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CompatibilityError(f"Expected a JSON object: {path.name}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _inside(root: Path, name: str) -> Path:
    if not name or "\\" in name or ":" in name or name.startswith("/"):
        raise CompatibilityError("Expected repository-relative evidence path")
    if any(part in {"", ".", ".."} for part in name.split("/")):
        raise CompatibilityError("Unsafe evidence path")
    resolved = (root / name).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise CompatibilityError("Evidence path escapes project root")
    return resolved


def _comparison(before: Any, after: Any) -> dict[str, Any]:
    result = {
        "equal": before == after,
        "baseline_sha256": _object_hash(before),
        "candidate_sha256": _object_hash(after),
    }
    if before != after:
        result["baseline"] = before
        result["candidate"] = after
    return result


def audit_frozen_files(root: Path, manifest: Path, *, expected_count: int = 55) -> dict[str, Any]:
    """Verify raw bytes, including sealed reports; never normalize line endings."""
    expected = _json(manifest)
    if len(expected) != expected_count:
        raise CompatibilityError(f"Frozen file manifest must contain {expected_count} files")
    rows = []
    for name, digest in sorted(expected.items()):
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise CompatibilityError("Invalid frozen SHA-256")
        path = _inside(root, name)
        actual = _sha(path) if path.is_file() else None
        rows.append({"path": name, "expected": digest, "actual": actual, "equal": actual == digest})
    return {
        "manifest_sha256": _sha(manifest),
        "file_count": len(rows),
        "all_equal": all(row["equal"] for row in rows),
        "files": rows,
    }


def _keyed(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[tuple[str, ...], Any]:
    result = {}
    for row in rows:
        key = tuple(row[field] for field in fields)
        if any(not isinstance(part, str) or not part for part in key) or key in result:
            raise CompatibilityError("Duplicate or invalid stable evidence key")
        result[key] = row
    return result


def compare_assertions(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    """UUIDs, observation hashes, and actual-value diagnostic payloads are excluded."""
    old, new = _keyed(before, KEY_FIELDS), _keyed(after, KEY_FIELDS)
    rows = []
    for key in sorted(old.keys() | new.keys()):
        left = {f: old[key][f] for f in OUTCOME_FIELDS} if key in old else None
        right = {f: new[key][f] for f in OUTCOME_FIELDS} if key in new else None
        rows.append({"key": list(key), **_comparison(left, right)})
    return {
        "all_equal": old.keys() == new.keys() and all(row["equal"] for row in rows),
        "baseline_count": len(old),
        "candidate_count": len(new),
        "stable_key_fields": list(KEY_FIELDS),
        "compared_fields": list(OUTCOME_FIELDS),
        "rows": rows,
    }


def compare_retrieval(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare all 18 questions per path and exact aggregate metrics, without timing."""
    for report in (before, after):
        if (
            report.get("report_schema_version") != "rag-eval-v4"
            or report.get("label_contract_version") != "paired-graded-relevance-v2"
            or set(report.get("evaluations", {})) != set(PATHS)
        ):
            raise CompatibilityError("Expected the unchanged three-path RAG v4 contract")
    paths = {}
    for name in PATHS:
        left, right = before["evaluations"][name], after["evaluations"][name]
        old, new = _keyed(left["cases"], ("query_id",)), _keyed(right["cases"], ("query_id",))
        if len(old) != 18 or len(new) != 18:
            raise CompatibilityError("Each retrieval path requires 18 unique questions")
        cases = []
        for key in sorted(old.keys() | new.keys()):
            a = (
                {k: v for k, v in old[key].items() if k != "query_latency_ms"}
                if key in old
                else None
            )
            b = (
                {k: v for k, v in new[key].items() if k != "query_latency_ms"}
                if key in new
                else None
            )
            cases.append({"query_id": key[0], **_comparison(a, b)})
        metrics = _comparison(left["metrics"], right["metrics"])
        paths[name] = {
            "question_count": 18,
            "cases": cases,
            "metrics": metrics,
            "all_equal": metrics["equal"] and all(row["equal"] for row in cases),
            "baseline_metrics": left["metrics"],
            "candidate_metrics": right["metrics"],
        }
    excluded = {"generated_at_utc", "indexing", "evaluations"}

    def stable_contract(report: dict[str, Any]) -> dict[str, Any]:
        stable = {k: v for k, v in report.items() if k not in excluded}
        for key in ("dataset", "knowledge_snapshot"):
            stable[key] = {k: v for k, v in stable[key].items() if k != "sha256"}
        return stable

    contract = _comparison(stable_contract(before), stable_contract(after))
    input_fingerprints = {
        key: _comparison(before[key]["sha256"], after[key]["sha256"])
        for key in ("dataset", "knowledge_snapshot")
    }
    return {
        "all_equal": contract["equal"] and all(p["all_equal"] for p in paths.values()),
        "question_count": 18,
        "path_count": 3,
        "question_path_count": 54,
        "excluded_per_question_fields": ["query_latency_ms"],
        "report_contract": contract,
        "input_byte_fingerprints_not_scores": input_fingerprints,
        "paths": paths,
    }


def compare_run(before: dict[str, Any], after: dict[str, Any], mode: str) -> dict[str, Any]:
    old, new = before["metadata"], after["metadata"]
    scenario_count, assertion_count = {"rule_only": (10, 11), "mocked_model": (12, 18)}[mode]
    for run in (before, after):
        meta = run["metadata"]
        if (
            meta.get("mode") != mode
            or meta.get("protocol_id") != "p0-01.v1"
            or meta.get("partial_suite") is not False
            or meta.get("trial_count") != 1
            or meta.get("scenario_count") != scenario_count
            or len(set(meta.get("scenario_ids", []))) != scenario_count
            or len(run["assertions"]) != assertion_count
            or {row["case_id"] for row in run["assertions"]} != set(meta["scenario_ids"])
            or meta.get("real_model_calls") != 0
            or meta.get("live_status") != "not_run"
        ):
            raise CompatibilityError("Run does not contain the complete offline P0-01 mode")
    invariants = {field: _comparison(old[field], new[field]) for field in CONTRACT_FIELDS}
    outcomes = compare_assertions(before["assertions"], after["assertions"])
    subreports = {}
    if mode == "rule_only":
        expected = {"retrieval-v4", "recommendation-contract"}
        if set(before["subreports"]) != expected or set(after["subreports"]) != expected:
            raise CompatibilityError("Required P0-01 subreports are missing or unexpected")
        subreports["retrieval"] = compare_retrieval(
            before["subreports"]["retrieval-v4"], after["subreports"]["retrieval-v4"]
        )
        old_rec = before["subreports"]["recommendation-contract"]
        new_rec = after["subreports"]["recommendation-contract"]
        for contract in (old_rec, new_rec):
            if contract.get("case_count") != 12 or contract.get("status") != "pass":
                raise CompatibilityError("Expected 12 passing recommendation data contracts")
        subreports["recommendation_contract"] = {"case_count": 12, **_comparison(old_rec, new_rec)}
    elif before["subreports"] or after["subreports"]:
        raise CompatibilityError("Unexpected mocked-model subreport")
    score_equal = outcomes["all_equal"] and all(
        value.get("all_equal", value.get("equal")) for value in subreports.values()
    )
    return {
        "mode": mode,
        "baseline_manifest_hash": before["manifest_hash"],
        "candidate_manifest_hash": after["manifest_hash"],
        "scenario_count": scenario_count,
        "assertion_count": assertion_count,
        "contract_fingerprints_equal": all(value["equal"] for value in invariants.values()),
        "fingerprints": invariants,
        "baseline_raw_fingerprints": {
            field: _comparison(old[field], new[field]) for field in RAW_FINGERPRINT_FIELDS
        },
        "scores_equal": score_equal,
        "assertions": outcomes,
        "subreports": subreports,
        "non_invariant_context": {
            field: {
                "baseline": old.get(field),
                "candidate": new.get(field),
                "equal": old.get(field) == new.get(field),
            }
            for field in (
                "code_hash",
                "environment_hash",
                "tested_commit",
                "source_dirty",
                "provisional",
            )
        },
        "baseline_environment": old.get("environment"),
        "candidate_environment": new.get("environment"),
    }


def _baselines(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    index_path, trust_path = (
        root / "config/quality_baseline_index.v1.json",
        root / "config/quality_trust.v1.json",
    )
    index, trust = _json(index_path), _json(trust_path)
    if index.get("protocol_id") != "p0-01.v1":
        raise CompatibilityError("Wrong baseline index protocol")
    runs, entries = {}, {}
    for mode in MODES:
        entry = index["accepted"][mode]
        baseline = load_run(_inside(root, entry["directory"]))
        acceptance = _json(_inside(root, entry["acceptance_record"]))
        digest, identifier = baseline["manifest_hash"], entry["acceptance_id"]
        if (
            entry["manifest_hash"] != digest
            or trust["accepted_baselines"].get(identifier) != digest
            or trust["latest_accepted_baselines"].get(mode) != identifier
            or acceptance.get("acceptance_id") != identifier
            or acceptance.get("manifest_hash") != digest
            or acceptance.get("run", {}).get("manifest_hash") != digest
            or baseline["metadata"].get("provisional") is not False
        ):
            raise CompatibilityError("Local baseline index, seal, acceptance and trust disagree")
        runs[mode], entries[mode] = baseline, entry
    return runs, {
        "index_sha256": _sha(index_path),
        "trust_sha256": _sha(trust_path),
        "entries": entries,
        "verification_scope": "local index, trust, acceptance and sealed bytes; no remote CI revalidation",
    }


def _run_cli(root: Path, out: Path, mode: str) -> dict[str, Any]:
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-B",
        str(root / "scripts/run_quality_eval.py"),
        "--project-root",
        str(root),
        "run",
        "--mode",
        mode,
        "--out",
        str(out / mode),
    ]
    log = out / f"{mode}.log"
    environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            command,
            cwd=root,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=600,
        )
    record = {
        "command": command,
        "exit_code": result.returncode,
        "log": log.name,
        "log_sha256": _sha(log),
    }
    (out / f"{mode}-invocation.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    if result.returncode:
        raise CompatibilityError(f"Original {mode} CLI failed; inspect {log.name}")
    return record


def run_bridge(root: Path, out: Path) -> dict[str, Any]:
    """Create fresh evidence only. A failed/incomplete bridge always has exit code 2."""
    root, out = root.resolve(), out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {
        "schema_version": "p0-02-compatibility-bridge.v1",
        "kind": "compatibility bridge",
        "status": "error",
        "exit_code": 2,
        "started_at": datetime.now(UTC).isoformat(),
        "formal_regression": False,
        "baseline_acceptance_performed": False,
        "limitations": [
            "Local compatibility evidence only; this does not run or accept the formal regression gate.",
            "Windows and the accepted Linux baseline have different environment fingerprints.",
            "Raw input/evaluator byte fingerprints are recorded separately from stable scores; "
            "the 55-file pre-development manifest establishes local byte preservation.",
            "New P0-02 code changes the full source fingerprint and remains outside old policy acceptance.",
            "Unchanged failures remain failures; score equality is not correctness or live accuracy.",
            "Recommendation checks cover 12 data contracts, not live-model recommendation quality.",
        ],
        "invocations": {},
        "modes": {},
    }
    manifest = root / "data/runtime/p002-development/p001-frozen-files.json"
    try:
        report["frozen_files_before"] = audit_frozen_files(root, manifest)
        if not report["frozen_files_before"]["all_equal"]:
            raise CompatibilityError("Frozen P0-01 file bytes differ before execution")
        baselines, report["baseline_index"] = _baselines(root)
        for mode in MODES:
            report["invocations"][mode] = _run_cli(root, out, mode)
            candidate = load_run(out / mode)
            report["modes"][mode] = compare_run(baselines[mode], candidate, mode)
        report["frozen_files_after"] = audit_frozen_files(root, manifest)
        report["frozen_sources_unchanged"] = (
            report["frozen_files_after"]["all_equal"]
            and report["frozen_files_before"] == report["frozen_files_after"]
        )
        report["contract_fingerprints_equal"] = all(
            mode["contract_fingerprints_equal"] for mode in report["modes"].values()
        )
        report["baseline_raw_fingerprints_equal"] = all(
            item["equal"]
            for mode in report["modes"].values()
            for item in mode["baseline_raw_fingerprints"].values()
        )
        report["scores_equal"] = all(mode["scores_equal"] for mode in report["modes"].values())
        report["scenario_count"] = sum(mode["scenario_count"] for mode in report["modes"].values())
        report["assertion_count"] = sum(
            mode["assertion_count"] for mode in report["modes"].values()
        )
        passed = all(
            report[key]
            for key in ("frozen_sources_unchanged", "contract_fingerprints_equal", "scores_equal")
        )
        report["status"], report["exit_code"] = ("pass", 0) if passed else ("fail", 2)
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        report["ended_at"] = datetime.now(UTC).isoformat()
        (out / "compatibility-bridge.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local P0-02/P0-01 compatibility bridge; not a formal gate"
    )
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--out", type=Path, required=True, help="New evidence directory; never overwritten"
    )
    args = parser.parse_args(argv)
    try:
        result = run_bridge(args.project_root, args.out)
    except OSError as exc:
        print(
            f"Compatibility bridge could not create evidence: {type(exc).__name__}", file=sys.stderr
        )
        return 2
    print(
        json.dumps(
            {key: result[key] for key in ("kind", "status", "exit_code")}, ensure_ascii=False
        )
    )
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
