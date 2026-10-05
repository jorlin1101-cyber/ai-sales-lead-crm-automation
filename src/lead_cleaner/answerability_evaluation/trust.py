"""Independent P0-02 trust roots and append-only human-review interpretation."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .reports import OBSERVATION_FIELDS, ReportError, content_hash, key, parse_json

TRUST_PATH = "config/quality_answerability_trust.v1.json"
ISSUES_PATH = "config/quality_answerability_known_issues.v1.json"
INDEX_PATH = "config/quality_answerability_baseline_index.v1.json"
EMPTY_REVIEW_SET: dict[str, Any] = {"review_set_id": "empty", "reviews": []}


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, encoding="utf-8"
    ).stdout.strip()


def require_current_ref(root: Path, trusted_ref: str) -> None:
    if (
        len(trusted_ref) != 40
        or any(c not in "0123456789abcdef" for c in trusted_ref)
        or trusted_ref != git(root, "rev-parse", "refs/remotes/origin/main")
    ):
        raise ReportError("Trust must use the exact current origin/main SHA")


def safe_relative(value: str) -> str:
    if (
        not value
        or "\\" in value
        or ":" in value
        or value.startswith(("/", "-"))
        or any(p in {"", ".", ".."} for p in value.split("/"))
    ):
        raise ReportError("Unsafe repository-relative path")
    return value


def trusted_json(root: Path, trusted_ref: str, path: str) -> dict[str, Any]:
    require_current_ref(root, trusted_ref)
    value = parse_json(git(root, "show", trusted_ref + ":" + safe_relative(path)))
    if not isinstance(value, dict):
        raise ReportError("Trusted JSON must be an object")
    return value


def verify_protected_files(root: Path, trusted_ref: str) -> dict[str, Any]:
    require_current_ref(root, trusted_ref)
    script = git(root, "show", trusted_ref + ":scripts/check_quality_policy.py")
    result = subprocess.run(
        [sys.executable, "-c", script, "--root", str(root), "--trusted-ref", trusted_ref],
        capture_output=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise ReportError(
            "Trusted policy guard rejected protected-file changes: " + result.stdout.strip()
        )
    return {"trusted_ref": trusted_ref, "guard_output": result.stdout.strip()}


def load_trust_context(root: Path, trusted_ref: str) -> dict[str, Any]:
    value = trusted_json(root, trusted_ref, TRUST_PATH)
    if value.get("protocol_id") != "p0-02.v1":
        raise ReportError("Trust configuration belongs to a different protocol")
    issues = trusted_json(root, trusted_ref, ISSUES_PATH)["issues"]
    return value | {
        "trusted_ref": trusted_ref,
        "known_issues_hash": content_hash(issues),
        "verified_artifacts": [],
    }


def effective_assertions(
    run: Mapping[str, Any],
    review_set: Mapping[str, Any] | None,
    trust_context: Mapping[str, Any],
    *,
    dataset: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str, list[str]]:
    fixed = dict(review_set) if review_set is not None else EMPTY_REVIEW_SET
    reviews = fixed.get("reviews")
    digest = content_hash(fixed)
    if not isinstance(reviews, list) or not fixed.get("review_set_id"):
        raise ReportError("Invalid fixed review set")
    if reviews and digest not in trust_context.get("accepted_review_set_hashes", []):
        raise ReportError("Review set has no trusted approval")
    rows = {key(row): dict(row) for row in run["assertions"]}
    records: dict[str, dict[str, Any]] = {}
    relevant: dict[str, dict[str, Any]] = {}
    required = (
        "review_id",
        "run_manifest_hash",
        "output_hash",
        "rubric_hash",
        "reviewer",
        "role",
        "reason",
        "reviewed_at",
    )
    for review in reviews:
        if not isinstance(review, dict) or any(
            not isinstance(review.get(field), str) or not review[field].strip()
            for field in required
        ):
            raise ReportError("Missing review identity or audit field")
        identifier = review["review_id"]
        if identifier in records or review.get("verdict") not in {"pass", "fail", "needs_review"}:
            raise ReportError("Duplicate review or invalid verdict")
        identity = key(review.get("key", []))
        records[identifier] = review
        if review["run_manifest_hash"] != run["manifest_hash"]:
            continue
        row = rows.get(identity)
        if (
            row is None
            or row.get("manual_review") is not True
            or row["execution_status"] != "completed"
            or row["behavior_status"] != "needs_review"
        ):
            raise ReportError("Review cannot override automatic or unexecuted results")
        if review["output_hash"] != row["observation_hash"] or review["rubric_hash"] != run[
            "metadata"
        ].get("rubric_hash", run["metadata"]["evaluator_hash"]):
            raise ReportError("Review observation or rubric binding mismatch")
        relevant[identifier] = review
    replaced = set()
    for identifier, review in records.items():
        previous = review.get("supersedes_review_id")
        if previous is None:
            continue
        earlier = records.get(previous)
        if (
            earlier is None
            or earlier["run_manifest_hash"] != review["run_manifest_hash"]
            or key(earlier["key"]) != key(review["key"])
            or earlier["reviewer"].strip().casefold() != review["reviewer"].strip().casefold()
        ):
            raise ReportError("A correction must supersede the same reviewer's same assertion")
        visited = {identifier}
        cursor = previous
        while cursor is not None:
            if cursor in visited:
                raise ReportError("Cyclic review supersession")
            visited.add(cursor)
            cursor = records[cursor].get("supersedes_review_id")
        replaced.add(previous)
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for identifier, review in relevant.items():
        if identifier not in replaced:
            grouped.setdefault(key(review["key"]), []).append(review)
    for identity, judgments in grouped.items():
        verdicts = {r["verdict"] for r in judgments}
        roles = run["metadata"].get("review_required_roles", ["developer", "sales"])
        if len(roles) != 2 or set(roles) != {"developer", "sales"}:
            raise ReportError("Invalid review role requirements")
        assignments: set[frozenset[str]] = {frozenset()}
        for role in roles:
            identities = {r["reviewer"].strip().casefold() for r in judgments if r["role"] == role}
            assignments = {
                used | {identity}
                for used in assignments
                for identity in identities
                if identity not in used
            }
        verdict = next(iter(verdicts)) if len(verdicts) == 1 and assignments else "needs_review"
        row = rows[identity]
        if verdict != "needs_review" and row["assertion_id"] in {
            "answer_content",
            "grounding",
            "clarification",
        }:
            from .checks import expected_keys, score_observation

            if dataset is None or any(
                dataset.get(field) != run["metadata"].get(field)
                for field in ("dataset_hash", "knowledge_hash")
            ):
                raise ReportError(
                    "Semantic review requires the independently loaded matching dataset"
                )
            if expected_keys(dataset, run["metadata"]["mode"]) != run["metadata"]["expected_keys"]:
                raise ReportError("Semantic review dataset has different planned assertions")
            semantics = [r.get("semantic") for r in judgments]
            if any(not isinstance(s, dict) for s in semantics):
                raise ReportError("Semantic assertion requires complete claim/action adjudication")
            if len({content_hash(s) for s in semantics}) != 1:
                verdict = "needs_review"
            else:
                case = next(c for c in dataset["cases"] if c["case_id"] == row["case_id"])
                turn = next(t for t in case["turns"] if t["turn_id"] == row["turn_id"])
                observation = next(
                    o
                    for o in run["observations"]
                    if key(o, OBSERVATION_FIELDS) == key(row, OBSERVATION_FIELDS)
                )
                try:
                    scored = score_observation(
                        turn, dataset["snapshots"][case["snapshot_id"]], observation, semantics[0]
                    )
                except (ValueError, KeyError, TypeError) as exc:
                    raise ReportError("Semantic review content is invalid") from exc
                computed = next(r for r in scored if r["assertion_id"] == row["assertion_id"])
                if computed["behavior_status"] != verdict or any(
                    r.get("failure_type", computed["failure_type"]) != computed["failure_type"]
                    for r in judgments
                ):
                    raise ReportError(
                        "Human verdict disagrees with independently recomputed semantics"
                    )
                rows[identity] = computed
        rows[identity]["behavior_status"] = verdict
        rows[identity]["review_ids"] = sorted(r["review_id"] for r in judgments)
        if rows[identity]["behavior_status"] == "fail" and row["assertion_id"] not in {
            "answer_content",
            "grounding",
            "clarification",
        }:
            failures = {r.get("failure_type", "human_review_failure") for r in judgments}
            if len(failures) != 1 or not all(isinstance(f, str) and f for f in failures):
                raise ReportError("Human failure signatures disagree")
            rows[identity]["failure_type"] = next(iter(failures))
    return list(rows.values()), digest, sorted(relevant)
