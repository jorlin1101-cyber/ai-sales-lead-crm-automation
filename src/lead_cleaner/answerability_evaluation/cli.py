"""P0-02 local execution, trusted checks and reviewable acceptance proposals."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from lead_cleaner.answerability_evaluation.checks import expected_keys, expected_retrieval_keys
from lead_cleaner.answerability_evaluation.dataset import load_dataset
from lead_cleaner.answerability_evaluation.gates import (
    accept_baselines,
    evaluate_gate,
    write_decision,
)
from lead_cleaner.answerability_evaluation.metrics import summarize_replies
from lead_cleaner.answerability_evaluation.provenance import verify_github_artifacts
from lead_cleaner.answerability_evaluation.registry import ACTIVE_PROTOCOL, protocol_spec
from lead_cleaner.answerability_evaluation.reports import (
    ReportError,
    load_run,
    read_json,
    write_record,
)
from lead_cleaner.answerability_evaluation.runner import run_suite
from lead_cleaner.answerability_evaluation.trust import (
    EMPTY_REVIEW_SET,
    load_trust_context,
    safe_relative,
    trusted_json,
    verify_protected_files,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="P0-02: evaluation evidence is not product approval"
    )
    result.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[3])
    commands = result.add_subparsers(dest="command", required=True)
    archive = commands.add_parser("verify-archive")
    archive.add_argument("--run", type=Path, action="append", required=True)
    run = commands.add_parser("run")
    run.add_argument("--mode", choices=["rule_only", "mocked_model"], required=True)
    run.add_argument("--out", type=Path, required=True)
    check = commands.add_parser("check")
    check.add_argument("--gate", choices=["inventory", "regression", "behavior"], required=True)
    check.add_argument("--run", type=Path, action="append", required=True)
    check.add_argument("--candidate-sha", required=True)
    check.add_argument("--trusted-ref")
    check.add_argument("--review-set", default="empty")
    check.add_argument("--out", type=Path, required=True)
    review = commands.add_parser("review-template")
    review.add_argument("--run", type=Path, action="append", required=True)
    review.add_argument("--out", type=Path, required=True)
    accept = commands.add_parser("accept")
    accept.add_argument("--run", type=Path, action="append", required=True)
    accept.add_argument("--trusted-ref", required=True)
    accept.add_argument("--review-set", required=True)
    accept.add_argument("--approvals", type=Path, required=True)
    accept.add_argument("--report-index", type=Path, required=True)
    accept.add_argument("--out", type=Path, required=True)
    return result


def _reviews(value: str) -> dict[str, Any]:
    return EMPTY_REVIEW_SET if value == "empty" else read_json(Path(value))


def _hydrate_baseline_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Resolve every immutable baseline against the repository, never process cwd."""
    if not isinstance(record, dict) or not isinstance(record.get("run"), dict):
        raise ReportError("Invalid trusted baseline record")
    stored = record["run"].get("directory")
    if not isinstance(stored, str) or not stored:
        raise ReportError("Trusted baseline has no archive directory")
    directory = Path(stored)
    if not directory.is_absolute():
        directory = root / safe_relative(stored.replace("\\", "/"))
    hydrated = {**record, "run": load_run(directory)}
    if hydrated["run"]["metadata"]["protocol_id"] != ACTIVE_PROTOCOL:
        raise ReportError("Archived baseline uses an inactive protocol")
    if hydrated["run"]["manifest_hash"] != record.get("manifest_hash"):
        raise ReportError("Archived baseline does not match trusted index")
    initial = record.get("initial_baseline")
    if initial is not None:
        hydrated["initial_baseline"] = _hydrate_baseline_record(root, initial)
    return hydrated


def _baselines(root: Path, reference: str) -> dict[str, Any]:
    index = trusted_json(root, reference, protocol_spec(ACTIVE_PROTOCOL)["index_path"])
    if index.get("protocol_id") != ACTIVE_PROTOCOL:
        raise ReportError("Wrong baseline protocol")
    records = {}
    for mode, value in index["accepted"].items():
        record = (
            trusted_json(root, reference, safe_relative(value)) if isinstance(value, str) else value
        )
        records[mode] = _hydrate_baseline_record(root, record)
    return records


def _active_runs(paths: list[Path]) -> list[dict[str, Any]]:
    runs = [load_run(path) for path in paths]
    if any(run["metadata"]["protocol_id"] != ACTIVE_PROTOCOL for run in runs):
        raise ReportError("Inactive reports are read-only; use verify-archive instead")
    return runs


def _check(args: argparse.Namespace) -> dict[str, Any]:
    root = args.project_root.resolve()
    runs = _active_runs(args.run)
    trust: dict[str, Any] = {}
    baselines: dict[str, Any] = {}
    issues = []
    if args.trusted_ref:
        verify_protected_files(root, args.trusted_ref)
        trust = load_trust_context(root, args.trusted_ref, protocol_id=ACTIVE_PROTOCOL)
        baselines = _baselines(root, args.trusted_ref)
        issues = trusted_json(
            root, args.trusted_ref, protocol_spec(ACTIVE_PROTOCOL)["issues_path"]
        )["issues"]
    if args.gate == "regression" and not args.trusted_ref:
        raise ReportError(
            "Regression requires current accepted main, not a local self-signed baseline"
        )
    if args.review_set != "empty" and not args.trusted_ref:
        raise ReportError("Human adjudications require an independently approved review set")
    dataset = load_dataset(root, ACTIVE_PROTOCOL)
    modes = [run["metadata"]["mode"] for run in runs]
    decision = evaluate_gate(
        args.gate,
        runs,
        candidate_sha=args.candidate_sha,
        expected_keys_by_mode={m: expected_keys(dataset, m) for m in modes},
        expected_retrieval_keys_by_mode={m: expected_retrieval_keys(dataset, m) for m in modes},
        baselines=baselines,
        known_issues=issues,
        review_set=_reviews(args.review_set),
        trust_context=trust,
        required_modes=["rule_only", "mocked_model"] if args.gate == "behavior" else modes,
        dataset=dataset,
    )
    decision["effective_metrics"] = {
        run["metadata"]["mode"]: summarize_replies(dataset, run["observations"], rows)
        for run in runs
        if (rows := decision["effective_assertions"].get(run["metadata"]["mode"]))
    }
    write_decision(args.out, decision)
    return decision


def _template(args: argparse.Namespace) -> None:
    from lead_cleaner.answerability_evaluation.reports import content_hash, key, OBSERVATION_FIELDS

    records = []
    for run in _active_runs(args.run):
        observations = {key(o, OBSERVATION_FIELDS): o for o in run["observations"]}
        for row in run["assertions"]:
            if row["behavior_status"] != "needs_review":
                continue
            obs = observations[key(row, OBSERVATION_FIELDS)]
            for role in ("developer", "sales"):
                records.append(
                    {
                        "review_id": "",
                        "key": list(key(row)),
                        "run_manifest_hash": run["manifest_hash"],
                        "output_hash": content_hash(obs),
                        "rubric_hash": run["metadata"]["rubric_hash"],
                        "source_manifest_hash": run["metadata"]["source_manifest_hash"],
                        "group_source_hash": run["metadata"]["group_source_hash"],
                        "reviewer": "",
                        "role": role,
                        "reason": "",
                        "reviewed_at": "",
                        "verdict": "needs_review",
                        "semantic": {
                            "observation_hash": content_hash(obs),
                            "rubric_version": protocol_spec(ACTIVE_PROTOCOL)["rubric_version"],
                            "claims_complete": False,
                            "completeness_rationale": "",
                            "claims": [],
                            "answered_facets": [],
                            "action_appropriate": None,
                            "gap_disclosed": None,
                            "clarification_appropriate": None,
                            "reply_action": None,
                        },
                    }
                )
    write_record(args.out, {"review_set_id": "draft-not-approved", "reviews": records})


def _canonical_records(value: Any, targets: dict[str, tuple[str, str]]) -> Any:
    """Repoint only newly accepted records; preserve all historical initial records."""
    result = copy.deepcopy(value)
    if isinstance(result, dict):
        for name, child in result.items():
            result[name] = _canonical_records(child, targets)
        identity = result.get("acceptance_id")
        if isinstance(identity, str) and identity in targets:
            target, manifest = targets[identity]
            if result.get("manifest_hash") != manifest or not isinstance(result.get("run"), dict):
                raise ReportError("Acceptance record does not match its staged archive")
            result["run"]["directory"] = target
    elif isinstance(result, list):
        result = [_canonical_records(child, targets) for child in result]
    return result


def _accept(args: argparse.Namespace) -> dict[str, Any]:
    root = args.project_root.resolve()
    if args.out.exists():
        raise ReportError("Acceptance proposal output already exists")
    _active_runs(args.run)
    verify_protected_files(root, args.trusted_ref)
    trust = load_trust_context(root, args.trusted_ref, protocol_id=ACTIVE_PROTOCOL)
    entries = read_json(args.report_index)["reports"]
    trust["verified_artifacts"] = verify_github_artifacts(
        root, args.trusted_ref, entries, protocol_id=ACTIVE_PROTOCOL
    )
    dataset = load_dataset(root, ACTIVE_PROTOCOL)
    runs = []
    for path in args.run:
        mode = load_run(path)["metadata"]["mode"]
        runs.append(
            load_run(
                path,
                expected_keys=expected_keys(dataset, mode),
                expected_retrieval_keys=expected_retrieval_keys(dataset, mode),
            )
        )
    proposal = accept_baselines(
        runs,
        previous=_baselines(root, args.trusted_ref),
        known_issues=trusted_json(
            root, args.trusted_ref, protocol_spec(ACTIVE_PROTOCOL)["issues_path"]
        )["issues"],
        approvals=read_json(args.approvals),
        trust_context=trust,
        review_set=_reviews(args.review_set),
        dataset=dataset,
    )
    spec = protocol_spec(ACTIVE_PROTOCOL)
    targets = {}
    for unit in proposal["accepted"].values():
        identity = safe_relative(unit["acceptance_id"])
        if len(Path(identity).parts) != 1:
            raise ReportError("Acceptance ID must be a single safe path component")
        targets[identity] = (f"{spec['baseline_directory']}/{identity}/run", unit["manifest_hash"])
    args.out.mkdir(parents=True, exist_ok=False)
    for unit in proposal["accepted"].values():
        destination = args.out / targets[unit["acceptance_id"]][0]
        shutil.copytree(unit["run"]["directory"], destination)
        unit["run"] = load_run(destination)
        if destination.resolve().is_relative_to(root):
            unit["run"]["directory"] = destination.resolve().relative_to(root).as_posix()
    write_record(args.out / "proposal.json", proposal)
    canonical = _canonical_records(proposal, targets)
    write_record(
        args.out / "archive-installation.json",
        {
            "status": "proposal_only_not_installed",
            "protocol_id": ACTIVE_PROTOCOL,
            "archives": [
                {"staged": str(args.out / path), "repository_path": path, "manifest_hash": manifest}
                for path, manifest in targets.values()
            ],
            "required_action": "Review and commit archives, index, trust and issues together",
        },
    )
    write_record(
        args.out / "proposed-config" / Path(protocol_spec(ACTIVE_PROTOCOL)["index_path"]).name,
        {
            "protocol_id": ACTIVE_PROTOCOL,
            "initial": canonical["initial"],
            "accepted": canonical["accepted"],
        },
    )
    write_record(
        args.out / "proposed-config" / Path(protocol_spec(ACTIVE_PROTOCOL)["issues_path"]).name,
        {"protocol_id": ACTIVE_PROTOCOL, "issues": proposal["known_issues"]},
    )
    proposed_trust = {
        name: value
        for name, value in trust.items()
        if name not in {"trusted_ref", "known_issues_hash", "verified_artifacts"}
    }
    proposed_trust.update(
        accepted_baselines=proposal["accepted_baselines"],
        latest_accepted_baselines=proposal["latest_accepted_baselines"],
    )
    write_record(
        args.out / "proposed-config" / Path(protocol_spec(ACTIVE_PROTOCOL)["trust_path"]).name,
        proposed_trust,
    )
    return {
        "proposal": str(args.out),
        "accepted_modes": sorted(proposal["accepted"]),
        "status": "prepared_for_trusted_git_acceptance",
        "product_release_status": "not_evaluated",
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "verify-archive":
            for path in args.run:
                archived = load_run(path)
                print(
                    json.dumps(
                        {
                            "protocol_id": archived["metadata"]["protocol_id"],
                            "manifest_hash": archived["manifest_hash"],
                            "status": "sealed_bytes_verified",
                            "business_approval": False,
                        }
                    )
                )
            return 0
        if args.command == "run":
            run = run_suite(args.project_root.resolve(), args.mode, args.out, ACTIVE_PROTOCOL)
            errors = sum(o["execution_status"] != "completed" for o in run["observations"]) + sum(
                r["execution_status"] != "completed" for r in run["retrieval"]
            )
            print(
                json.dumps(
                    {
                        "manifest_hash": run["manifest_hash"],
                        "mode": args.mode,
                        "provisional": run["metadata"]["provisional"],
                        "execution_errors": errors,
                        "directory": run["directory"],
                    },
                    ensure_ascii=False,
                )
            )
            return 2 if errors else 0
        if args.command == "check":
            result = _check(args)
            print(
                json.dumps(
                    {
                        "exit_code": result["exit_code"],
                        "provisional": result["provisional"],
                        "reasons": result["reasons"],
                    },
                    ensure_ascii=False,
                )
            )
            return int(result["exit_code"])
        if args.command == "review-template":
            _template(args)
            print(json.dumps({"review_template": str(args.out), "status": "draft"}))
            return 0
        print(json.dumps(_accept(args), ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        code = 3 if isinstance(error, (ReportError, subprocess.CalledProcessError)) else 2
        print(json.dumps({"exit_code": code, "error": str(error)}, ensure_ascii=False))
        return code
