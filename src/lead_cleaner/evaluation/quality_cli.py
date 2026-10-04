"""Command-line composition for the P0-01 quality tools."""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from lead_cleaner.evaluation._quality_summary import render_run_summary
from lead_cleaner.evaluation._quality_runtime import append_journal
from lead_cleaner.evaluation.quality_checks import (
    evaluate_assertions,
    recommendation_contract_report,
)
from lead_cleaner.evaluation.quality_context import (
    build_metadata,
    load_trust_context,
    read_json,
    trusted_json,
    verify_github_artifacts,
    verify_protected_files,
)
from lead_cleaner.evaluation.quality_report import evaluate_gate, load_run, seal_run, write_decision
from lead_cleaner.evaluation.quality_runner import load_cases, run_quality_suite
from lead_cleaner.evaluation.quality_schema import AssertionResult, CaseSpec, expected_keys
from lead_cleaner.rag.evaluation_report import run_keyword_evaluation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="P0-01 quality evaluation: execution is not business approval"
    )
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[3])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="produce a new sealed, isolated run")
    run.add_argument("--mode", choices=["rule_only", "mocked_model", "live"], required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--protocol", type=Path)
    run.add_argument("--allow-network", action="store_true")
    run.add_argument("--max-requests", type=int, default=60)
    run.add_argument("--api-key-env", default="QUALITY_MODEL_API_KEY")
    run.add_argument("--model", default=None)
    run.add_argument("--base-url", default="https://dashscope.aliyuncs.com/compatible-mode/v1")
    run.add_argument("--timeout", type=float, default=30.0)
    check = commands.add_parser("check", help="evaluate an immutable report; never calls a model")
    check.add_argument("--gate", choices=["inventory", "regression", "release"], required=True)
    check.add_argument("--run", type=Path, action="append", default=[])
    check.add_argument("--candidate-sha", required=True)
    check.add_argument("--baseline-index", type=Path)
    check.add_argument("--report-index", type=Path)
    check.add_argument("--review-set", default="empty")
    check.add_argument("--trusted-ref", default=None)
    check.add_argument("--profile", default="p0-01-ai-assisted.v1")
    check.add_argument("--out", type=Path)
    policy = commands.add_parser(
        "verify-policy", help="compare scoring inputs to an accepted remote commit"
    )
    policy.add_argument("--trusted-ref", required=True)
    return parser


def _protocol(root: Path, path: Path | None = None) -> dict[str, Any]:
    value = read_json(path or root / "config/quality_baseline.v1.json")
    expected = {"rule_only": (1, 10), "mocked_model": (1, 12), "live": (3, 10)}
    if value.get("protocol_id") != "p0-01.v1" or value.get("profile") != "p0-01-ai-assisted.v1":
        raise ValueError("unsupported quality protocol")
    for mode, (trials, count) in expected.items():
        if value.get("modes", {}).get(mode) != {"trials": trials, "case_count": count}:
            raise ValueError("mode matrix differs from the frozen v1 protocol")
    return value


def _cases(root: Path) -> list[dict[str, Any]]:
    cases = [CaseSpec.model_validate(case).model_dump(mode="json") for case in load_cases(root)]
    if len(cases) != 22 or len({case["case_id"] for case in cases}) != 22:
        raise ValueError("full v1 suite requires 22 unique scenarios")
    return cases


def _match_issues(results: list[dict[str, Any]], issues: list[dict[str, Any]]) -> None:
    fields = (
        "mode",
        "case_id",
        "probe_id",
        "checkpoint",
        "assertion_id",
        "failure_type",
        "severity",
    )
    for result in results:
        if result["behavior_status"] != "fail":
            continue
        matches = [
            issue
            for issue in issues
            if issue.get("status") == "open" and all(issue.get(f) == result.get(f) for f in fields)
        ]
        if len(matches) > 1:
            raise ValueError("ambiguous known issue match")
        if matches:
            result["known_issue_id"] = matches[0]["issue_id"]


def _run(args: argparse.Namespace) -> int:
    if args.out.exists():
        raise ValueError("output directory already exists")
    diagnostics = args.out.with_name(args.out.name + ".diagnostics")
    diagnostics.mkdir(parents=True, exist_ok=False)
    journal = diagnostics / "events.jsonl"
    append_journal(
        journal,
        {"event": "started", "mode": args.mode, "started_at": datetime.now(UTC).isoformat()},
    )
    try:
        code = _execute_run(args, journal)
    except BaseException as exc:
        append_journal(
            journal,
            {
                "event": "interrupted" if isinstance(exc, KeyboardInterrupt) else "error",
                "error_type": type(exc).__name__,
            },
        )
        raise
    append_journal(journal, {"event": "sealed", "exit_code": code})
    return code


def _execute_run(args: argparse.Namespace, journal: Path) -> int:
    root = args.project_root.resolve()
    if args.out.exists():
        raise ValueError("output directory already exists")
    protocol = _protocol(root, args.protocol)
    cases = _cases(root)
    if not 0 < args.max_requests <= protocol["live_max_requests"]:
        raise ValueError("request budget is outside the frozen protocol")
    live_config = None
    if args.mode == "live":
        if not args.allow_network:
            raise ValueError("live requires --allow-network")
        model = args.model or os.getenv("QUALITY_MODEL_NAME", "")
        if not model:
            raise ValueError("live requires an explicit model name")
        if urlparse(args.base_url).hostname not in protocol["allowed_live_hosts"]:
            raise ValueError("model endpoint is outside the frozen allowlist")
        live_config = {
            "api_key": os.getenv(args.api_key_env, ""),
            "model": model,
            "base_url": args.base_url,
            "timeout": args.timeout,
        }
    trials = protocol["modes"][args.mode]["trials"]
    expected = expected_keys(cases, args.mode, trials)
    started = datetime.now(UTC).isoformat()
    before = build_metadata(root, cases, args.mode, protocol)
    append_journal(journal, {"event": "fingerprints", "metadata": before})
    result = run_quality_suite(
        args.mode,
        project_root=root,
        cases=cases,
        trials=trials,
        max_requests=args.max_requests,
        allow_network=args.allow_network,
        live_config=live_config,
        journal_path=journal,
    )
    assertions = evaluate_assertions(cases, result["observations"], mode=args.mode, trials=trials)
    assertions = [AssertionResult.model_validate(row).model_dump(mode="json") for row in assertions]
    issues = read_json(root / "config/quality_known_issues.v1.json")["issues"]
    _match_issues(assertions, issues)
    subreports = {}
    if args.mode == "rule_only":
        subreports["retrieval-v4"] = run_keyword_evaluation(
            chunks_path=root / "data/knowledge_snapshot/knowledge_chunks.json",
            eval_queries_path=root / "data/rag_eval/eval_queries.json",
        )
        subreports["recommendation-contract"] = recommendation_contract_report(
            read_json(root / "data/recommendation_eval/golden_cases.json")
        )
    metadata = build_metadata(root, cases, args.mode, protocol)
    for field in (
        "code_hash",
        "evaluator_hash",
        "suite_hash",
        "knowledge_hash",
        "evaluation_data_hash",
        "environment_hash",
    ):
        if before.get(field) != metadata.get(field):
            raise ValueError("evaluated files changed during execution; diagnostics retained")
    metadata.update(result["metadata"])
    metadata.update(
        run_id=uuid4().hex,
        started_at=started,
        ended_at=datetime.now(UTC).isoformat(),
        expected_keys=expected,
        review_required_roles=["developer", "sales"],
    )
    if metadata.get("live_simulated") or metadata.get("partial_suite"):
        metadata["provisional"] = True
    raw = {
        "metadata": metadata,
        "observations": result["observations"],
        "assertions": assertions,
        "subreports": subreports,
    }
    raw["summary"] = render_run_summary(raw, cases)
    sealed = seal_run(args.out, raw, expected_keys=expected)
    failed_execution = any(row["execution_status"] != "completed" for row in assertions)
    print(
        json.dumps(
            {
                "run": str(args.out.resolve()),
                "mode": args.mode,
                "scenario_count": metadata["scenario_count"],
                "assertion_count": len(assertions),
                "business_failures": sum(r["behavior_status"] == "fail" for r in assertions),
                "needs_review": sum(r["behavior_status"] == "needs_review" for r in assertions),
                "provisional": metadata["provisional"],
                "manifest_hash": sealed.get("manifest_hash"),
                "real_model_calls": metadata["real_model_calls"],
            },
            ensure_ascii=False,
        )
    )
    return 2 if failed_execution else 0


def _load_baselines(root: Path, path: Path | None, trusted_ref: str | None) -> dict[str, Any]:
    if path is None:
        return {}
    resolved = path.resolve()
    if trusted_ref:
        index = trusted_json(root, trusted_ref, resolved.relative_to(root).as_posix())
    else:
        index = read_json(resolved)

    def record(entry: dict[str, Any]) -> dict[str, Any]:
        run_path = (root / entry["directory"]).resolve()
        if not run_path.is_relative_to(root):
            raise ValueError("baseline directory escaped project")
        baseline = load_run(run_path)
        if baseline["manifest_hash"] != entry["manifest_hash"]:
            raise ValueError("accepted baseline hash mismatch")
        item = {"acceptance_id": entry["acceptance_id"], "run": baseline}
        if "review_set" in entry:
            item["review_set"] = entry["review_set"]
        elif "review_set_path" in entry:
            review_path = (root / entry["review_set_path"]).resolve()
            if not review_path.is_relative_to(root):
                raise ValueError("review set escaped project")
            item["review_set"] = (
                trusted_json(root, trusted_ref, review_path.relative_to(root).as_posix())
                if trusted_ref
                else read_json(review_path)
            )
        return item

    baselines = {}
    for mode, entry in index.get("accepted", {}).items():
        item = record(entry)
        initial = index.get("initial", {}).get(mode) or entry.get("initial_baseline")
        if initial is not None:
            item["initial_baseline"] = record(initial)
        baselines[mode] = item
    return baselines


def _check(args: argparse.Namespace) -> int:
    root = args.project_root.resolve()
    protocol = _protocol(root)
    cases = _cases(root)
    expected = {
        mode: expected_keys(cases, mode, config["trials"])
        for mode, config in protocol["modes"].items()
    }
    trust: dict[str, Any] = {}
    issues = read_json(root / "config/quality_known_issues.v1.json")["issues"]
    if args.trusted_ref:
        trust = load_trust_context(root, args.trusted_ref)
        verify_protected_files(root, args.trusted_ref)
        issues = trusted_json(root, args.trusted_ref, "config/quality_known_issues.v1.json")[
            "issues"
        ]
    elif args.gate in {"regression", "release"}:
        raise ValueError(
            "regression/release requires an accepted --trusted-ref; inventory is available for bootstrap"
        )
    paths = list(args.run)
    provenance = []
    entries = []
    if args.report_index:
        index = read_json(args.report_index)
        entries = index["reports"]
        paths.extend(Path(entry["directory"]) for entry in entries)
        provenance = [entry["provenance"] for entry in entries if "provenance" in entry]
    if args.gate == "release":
        if args.profile != protocol["profile"]:
            raise ValueError("unknown release profile")
        if args.trusted_ref and entries:
            trust["verified_artifacts"] = verify_github_artifacts(root, args.trusted_ref, entries)
    runs = [load_run(path) for path in paths]
    baselines = _load_baselines(root, args.baseline_index, args.trusted_ref)
    reviews = None if args.review_set == "empty" else read_json(Path(args.review_set))
    decision = evaluate_gate(
        args.gate,
        runs,
        candidate_sha=args.candidate_sha,
        expected_keys_by_mode=expected,
        baselines=baselines,
        known_issues=issues,
        review_set=reviews,
        trust_context=trust,
        required_modes=protocol["required_modes"] if args.gate == "release" else None,
        provenance=provenance,
    )
    out = args.out or root / "data/runtime/quality-decisions" / uuid4().hex
    write_decision(out, decision)
    print(json.dumps({"decision": str(out.resolve()), **decision}, ensure_ascii=False))
    return int(decision["exit_code"])


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        if args.command == "check":
            return _check(args)
        load_trust_context(args.project_root.resolve(), args.trusted_ref)
        print(json.dumps(verify_protected_files(args.project_root.resolve(), args.trusted_ref)))
        return 0
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, KeyboardInterrupt) as exc:
        # Credentials are never CLI arguments and provider error payloads stay in the runner.
        code = 2 if args.command == "run" else 3
        print(
            json.dumps(
                {"exit_code": code, "error_type": type(exc).__name__, "message": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return code


if __name__ == "__main__":
    raise SystemExit(main())
