"""Append-only review interpretation; raw assertions are never changed."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._quality_storage import QualityReportError, assertion_key, object_hash

EMPTY_REVIEW_SET: dict[str, Any] = {"review_set_id": "empty", "reviews": []}


def effective_assertions(
    run: Mapping[str, Any],
    review_set: Mapping[str, Any] | None,
    trust_context: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], str, list[str]]:
    """Apply only approved, exactly bound reviews, preserving disagreements."""
    fixed_set = dict(review_set) if review_set is not None else EMPTY_REVIEW_SET
    digest = object_hash(fixed_set)
    reviews = fixed_set.get("reviews")
    if not isinstance(reviews, list) or not fixed_set.get("review_set_id"):
        raise QualityReportError("A review set requires an ID and an explicit reviews list.")
    if reviews and digest not in trust_context.get("accepted_review_set_hashes", []):
        raise QualityReportError("Review set has no independently verified approval.")
    rows = {assertion_key(row): dict(row) for row in run["assertions"]}
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
            raise QualityReportError("Review is missing a required identity or audit field.")
        identifier = review["review_id"]
        if identifier in records:
            raise QualityReportError("Duplicate review ID in fixed review set.")
        if review.get("verdict") not in {"pass", "fail", "needs_review"}:
            raise QualityReportError("Invalid human-review verdict.")
        key = assertion_key(review.get("key", []))
        records[identifier] = review
        if review["run_manifest_hash"] != run["manifest_hash"]:
            continue
        row = rows.get(key)
        if (
            row is None
            or row.get("manual_review") is not True
            or row["execution_status"] != "completed"
            or row["behavior_status"] != "needs_review"
        ):
            raise QualityReportError("Review cannot override an automatic or unexecuted assertion.")
        rubric = run["metadata"].get("rubric_hash", run["metadata"].get("evaluator_hash"))
        if review["output_hash"] != row.get("observation_hash") or review["rubric_hash"] != rubric:
            raise QualityReportError("Review output or rubric binding differs from the sealed run.")
        relevant[identifier] = review
    replaced: set[str] = set()
    for identifier, review in records.items():
        previous = review.get("supersedes_review_id")
        if previous is None:
            continue
        earlier = records.get(previous)
        if (
            earlier is None
            or previous == identifier
            or earlier["run_manifest_hash"] != review["run_manifest_hash"]
            or assertion_key(earlier["key"]) != assertion_key(review["key"])
        ):
            raise QualityReportError("Review correction must reference the same assertion and run.")
        visited = {identifier}
        cursor: str | None = previous
        while cursor is not None:
            if cursor in visited:
                raise QualityReportError("Review supersession graph contains a cycle.")
            visited.add(cursor)
            node = records.get(cursor)
            cursor = node.get("supersedes_review_id") if node else None
        replaced.add(previous)
    active: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for identifier, review in relevant.items():
        if identifier not in replaced:
            active.setdefault(assertion_key(review["key"]), []).append(review)
    for key, judgments in active.items():
        verdicts = {review["verdict"] for review in judgments}
        required_roles = set(run["metadata"].get("review_required_roles", []))
        # Match each required role to a distinct, consistently normalized identity.
        assignments: set[frozenset[str]] = {frozenset()}
        for role in required_roles:
            reviewers = {
                review["reviewer"].strip().casefold()
                for review in judgments
                if review["role"] == role
            }
            assignments = {
                used | {reviewer}
                for used in assignments
                for reviewer in reviewers
                if reviewer not in used
            }
        rows[key]["behavior_status"] = (
            next(iter(verdicts)) if len(verdicts) == 1 and assignments else "needs_review"
        )
        if rows[key]["behavior_status"] == "fail":
            failure_types = {
                review.get("failure_type", "human_review_failure") for review in judgments
            }
            if len(failure_types) != 1 or not all(
                isinstance(value, str) and value for value in failure_types
            ):
                raise QualityReportError(
                    "Failing human judgments require one unambiguous failure signature."
                )
            rows[key]["failure_type"] = next(iter(failure_types))
        rows[key]["review_ids"] = sorted(review["review_id"] for review in judgments)
    return list(rows.values()), digest, sorted(relevant)


def verify_provenance(
    run: Mapping[str, Any],
    provenance: list[dict[str, Any]],
    trust_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Match an external artifact index to provider-verified CI metadata."""
    candidates = [item for item in provenance if item.get("manifest_hash") == run["manifest_hash"]]
    if len(candidates) != 1:
        raise QualityReportError("Exactly one artifact provenance entry is required for each run.")
    supplied = candidates[0]
    fields = (
        "repository",
        "tested_commit",
        "workflow_sha",
        "run_id",
        "attempt",
        "artifact_id",
        "artifact_digest",
        "manifest_hash",
    )
    if any(supplied.get(field) in (None, "") for field in fields):
        raise QualityReportError("Artifact provenance is missing a required field.")
    if supplied["tested_commit"] != run["metadata"]["tested_commit"]:
        raise QualityReportError("Artifact provenance and tested commit differ.")
    verified = trust_context.get("verified_artifacts", [])
    if not any(all(item.get(field) == supplied[field] for field in fields) for item in verified):
        raise QualityReportError("Artifact provenance does not match externally verified CI data.")
    return {field: supplied[field] for field in fields}
