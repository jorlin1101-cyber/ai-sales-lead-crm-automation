"""Deterministic checks plus explicit, observation-bound semantic adjudication."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import date, datetime
from typing import Any

from lead_cleaner.answerability_evaluation.metrics import required_answerable, supported_facets
from lead_cleaner.answerability_evaluation.reports import content_hash

ASSERTION_IDS = ("execution", "facts_state", "answer_content", "grounding", "clarification")
RUBRIC = "answerability-rubric.v1"


def expected_keys(dataset: dict[str, Any], mode: str) -> list[list[str]]:
    return [
        ["p0-02.v1", mode, case["case_id"], "conversation", turn["turn_id"], name, "1"]
        for case in dataset["cases"]
        for turn in case["turns"]
        for name in ASSERTION_IDS
    ]


def expected_retrieval_keys(dataset: dict[str, Any], mode: str) -> list[list[str]]:
    return (
        [
            [case["case_id"], path]
            for case in dataset["cases"]
            if len(case["turns"]) == 1
            for path in ("raw_query", "runtime_rule_query", "runtime_fused_query")
        ]
        if mode == "rule_only"
        else []
    )


def _context(observation: dict[str, Any], snapshot: dict[str, Any]) -> tuple[set[str], list[str]]:
    chunks = {entry["chunk"]["chunk_id"]: entry for entry in snapshot["chunks"]}
    valid: set[str] = set()
    invalid: list[str] = []
    for item in observation.get("provided_context", []):
        identifier = item.get("chunk_id")
        if (
            identifier not in chunks
            or hashlib.sha256(item.get("text", "").encode("utf-8")).hexdigest()
            != chunks[identifier]["sha256"]
        ):
            invalid.append(str(identifier))
        else:
            valid.add(identifier)
    return valid, invalid


def _claim_point(claim: dict[str, Any], turn: dict[str, Any], entry: dict[str, Any]) -> date:
    evaluation = datetime.fromisoformat(turn.get("evaluation_time", ""))
    if evaluation.tzinfo is None or evaluation.utcoffset() is None:
        raise ValueError("Claim applicability requires an explicit evaluation time")
    scope = claim.get("temporal_scope", "current")
    if scope == "historical":
        historical = date.fromisoformat(claim.get("historical_date", ""))
        marker = claim.get("historical_date_text")
        if (
            historical >= evaluation.date()
            or not isinstance(marker, str)
            or not marker.strip()
            or marker not in claim["text"]
            or not str(claim.get("historical_rationale", "")).strip()
        ):
            raise ValueError(
                "Historical claims require an earlier date, output date span and rationale"
            )
        return historical
    if scope != "current" or claim.get("historical_date") is not None:
        raise ValueError("Invalid or contradictory claim temporal scope")
    basis = entry.get("validity_basis", "evaluation_time")
    if basis == "business_date":
        if not turn.get("business_date"):
            raise ValueError("Claim applicability requires the customer business date")
        return date.fromisoformat(turn["business_date"])
    if basis != "evaluation_time":
        raise ValueError("Unknown evidence validity basis")
    return evaluation.date()


def _within_period(entry: dict[str, Any], point: date) -> bool:
    return not (
        entry.get("valid_from")
        and point < date.fromisoformat(entry["valid_from"])
        or entry.get("valid_to")
        and point > date.fromisoformat(entry["valid_to"])
    )


def _validate_applicability(
    claim: dict[str, Any], turn: dict[str, Any], chunks: dict[str, Any]
) -> None:
    for ref in claim["evidence_refs"]:
        entry = chunks[ref["chunk_id"]]
        point = _claim_point(claim, turn, entry)
        if not _within_period(entry, point):
            raise ValueError("Claim uses expired or not-yet-applicable evidence")
        conflict_key = entry.get("conflict_key")
        if conflict_key:
            applicable_values = {
                item.get("conflict_value")
                for item in chunks.values()
                if item.get("conflict_key") == conflict_key
                and _within_period(item, _claim_point(claim, turn, item))
            }
            if len(applicable_values) > 1:
                raise ValueError("Claim is based on unresolved applicable conflicting evidence")
        if claim.get("temporal_scope", "current") == "current" and any(
            "unverified_validity" in facet.get("reasons", [])
            and ref["chunk_id"] in {e["chunk_id"] for e in facet.get("evidence_refs", [])}
            for facet in turn["facets"]
        ):
            raise ValueError("A current claim cannot resolve a known evidence-validity gap")


def adjudicate_claims(
    observation: dict[str, Any],
    turn: dict[str, Any],
    snapshot: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    """Validate observation-bound semantic judgments; gates verify the reviewer authority."""
    if (
        review.get("observation_hash") != content_hash(observation)
        or review.get("rubric_version") != RUBRIC
    ):
        raise ValueError("Review does not bind the original observation and rubric")
    if review.get("claims_complete") is not True or not review.get("completeness_rationale"):
        raise ValueError("Claim inventory must be exhaustively adjudicated")
    text = observation.get("reply_text", "")
    supplied, invalid = _context(observation, snapshot)
    if invalid:
        raise ValueError("Actual context differs from frozen evidence")
    facets = {f["facet_id"]: f for f in turn["facets"]}
    chunks = {entry["chunk"]["chunk_id"]: entry for entry in snapshot["chunks"]}
    raw_claims = review.get("claims")
    if not isinstance(raw_claims, list):
        raise ValueError("Missing claim inventory")
    # Derived citation results must not mutate or change the hash of a signed review.
    claims = deepcopy(raw_claims)
    response = observation.get("response") or {}
    citations = response.get("reply_draft", {}).get("source_ids", [])
    if not isinstance(citations, list) or any(not isinstance(item, str) for item in citations):
        raise ValueError("Malformed actual output citations")
    actual_citations = set(citations)
    seen: set[str] = set()
    seen_claims: set[tuple[int, int, str]] = set()
    for claim in claims:
        identifier = claim.get("claim_id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError("Duplicate or missing claim identity")
        seen.add(identifier)
        start, end = claim.get("start"), claim.get("end")
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(text)
            or claim.get("text") != text[start:end]
        ):
            raise ValueError("Claim span differs from original output")
        if not claim.get("proposition") or not claim.get("rationale"):
            raise ValueError("Atomic proposition and rationale are required")
        identity = (start, end, claim["proposition"])
        if identity in seen_claims:
            raise ValueError("The same atomic output claim cannot be counted twice")
        seen_claims.add(identity)
        facet_id = claim.get("facet_id")
        if facet_id is not None and facet_id not in facets:
            raise ValueError("Unknown facet association")
        if claim.get("verdict") not in {"supported", "unsupported", "contradicted", "unverifiable"}:
            raise ValueError("Unknown claim verdict")
        if claim.get("review_status") != "reviewed":
            raise ValueError("Unadjudicated claim cannot become a reviewed output")
        refs = claim.get("evidence_refs", [])
        if not isinstance(refs, list):
            raise ValueError("Claim evidence references must be a list")
        for ref in refs:
            chunk_id = ref.get("chunk_id")
            if chunk_id not in supplied or ref.get("sha256") != chunks[chunk_id]["sha256"]:
                raise ValueError("Claim references absent or modified provided context")
            a, b = ref.get("start"), ref.get("end")
            evidence_text = chunks[chunk_id]["chunk"]["text"]
            if (
                type(a) is not int
                or type(b) is not int
                or not 0 <= a < b <= len(evidence_text)
                or ref.get("quote") != evidence_text[a:b]
            ):
                raise ValueError("Claim evidence span differs from snapshot")
        if claim["verdict"] == "supported":
            if not refs:
                raise ValueError("Supported business claim needs actual evidence")
            _validate_applicability(claim, turn, chunks)
            if facet_id is not None:
                facet = facets[facet_id]
                if not facet["answerable"] or not any(
                    set(group) <= {r["chunk_id"] for r in refs} for group in facet["support_groups"]
                ):
                    raise ValueError(
                        "Claim cannot contradict corpus applicability or partial support"
                    )
        claim["citation_supported"] = bool(
            claim["verdict"] == "supported"
            and refs
            and {ref["chunk_id"] for ref in refs} <= actual_citations
            and actual_citations <= supplied
        )
    answered = review.get("answered_facets", [])
    if len(answered) != len(set(answered)) or not set(answered) <= set(facets):
        raise ValueError("Invalid answered facet inventory")
    for facet_id in answered:
        if not any(c.get("facet_id") == facet_id and c["verdict"] == "supported" for c in claims):
            raise ValueError("Answered facet lacks a supported claim")
    action = review.get("reply_action")
    if action not in {"answer", "partial", "full_refusal", "clarify"}:
        raise ValueError("Missing or invalid actual reply action")
    if (action in {"full_refusal", "clarify"} and claims) or (
        action in {"answer", "partial"} and not claims
    ):
        raise ValueError("Reply action contradicts the adjudicated substantive claims")
    for flag in ("action_appropriate", "gap_disclosed", "clarification_appropriate"):
        if type(review.get(flag)) is not bool:
            raise ValueError("Missing semantic action decision")
    required = {f["facet_id"] for f in turn["facets"] if f["required"]}
    return {
        "claims_complete": not any(c["verdict"] == "unverifiable" for c in claims),
        "claims": claims,
        "review_hash": content_hash(review),
        "reply_action": action,
        "addressed_required_facets": sorted(
            {c["facet_id"] for c in claims if c.get("facet_id") in required}
        ),
        "answered_required_facets": sorted(
            set(answered) & {f["facet_id"] for f in required_answerable(turn)}
        ),
        "context_supported_facets": sorted(supported_facets(turn, supplied)),
        "invalid_output_citations": sorted(actual_citations - supplied),
        "action_appropriate": review["action_appropriate"],
        "gap_disclosed": review["gap_disclosed"],
        "clarification_appropriate": review["clarification_appropriate"],
    }


def _facts(turn: dict[str, Any], observation: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    actual = {f["key"]: f for f in observation.get("facts", [])}
    ids = observation.get("message_id_map", {})
    for expected in turn.get("expected_facts", []):
        fact = actual.get(expected["key"])
        if (
            fact is None
            or fact.get("value") != expected["value"]
            or fact.get("status") not in expected["statuses"]
        ):
            errors.append("fact_value_or_status:" + expected["key"])
        elif fact.get("source_message_id") != ids.get(expected["source_turn_id"]):
            errors.append("fact_source:" + expected["key"])
    if (
        turn.get("expected_state") is not None
        and observation.get("state") != turn["expected_state"]
    ):
        errors.append("conversation_state")
    return errors


def _stage_failure(observation: dict[str, Any]) -> str | None:
    if observation["mode"] == "rule_only":
        return None
    stages = observation.get("stages", [])
    if len(stages) != 2 or {s.get("stage") for s in stages} != {"understanding", "generation"}:
        return "model_stage_inventory_incomplete"
    for stage in stages:
        expected, count = stage.get("expected_to_run"), stage.get("call_count")
        if type(expected) is not bool or type(count) is not int or count < 0:
            return "invalid_model_stage_record"
        if expected:
            if (
                count < 1
                or stage.get("provider_execution") != "succeeded"
                or stage.get("validation_result") != "accepted"
                or stage.get("error_type")
            ):
                return "required_model_stage_failed"
        elif (
            count
            or stage.get("provider_execution") != "not_called"
            or stage.get("validation_result") != "not_reached"
            or not str(stage.get("not_called_reason") or "").strip()
        ):
            return "unexplained_model_stage_skip"
    return None


def score_observation(
    turn: dict[str, Any],
    snapshot: dict[str, Any],
    observation: dict[str, Any],
    review: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    observed_status = observation["execution_status"]
    successful_reply = observation.get("api_status") == 200 and bool(observation.get("reply_text"))
    stage_failure = _stage_failure(observation) if successful_reply else None
    model_fallback = observed_status == "error" and stage_failure == "required_model_stage_failed"
    business_observable = successful_reply and (observed_status == "completed" or model_fallback)
    supplied, invalid = _context(observation, snapshot)
    semantic = (
        adjudicate_claims(observation, turn, snapshot, review)
        if review is not None and business_observable
        else None
    )
    facts_errors = _facts(turn, observation)
    default_details = {
        "claims_complete": False,
        "claims": [],
        "answered_required_facets": [],
        "addressed_required_facets": [],
        "reply_action": None,
        "context_supported_facets": sorted(supported_facets(turn, supplied)),
    }
    rows: list[dict[str, Any]] = []
    for name in ASSERTION_IDS:
        behavior: str | None = "pass"
        failure = None
        status = "completed"
        details: dict[str, Any] = {}
        if not business_observable:
            status = observed_status if observed_status != "completed" else "error"
            behavior = None
            failure = observation.get("error_type") or "missing_successful_reply"
        elif name == "execution":
            if observed_status != "completed" or stage_failure:
                status, behavior = "error", None
                failure = stage_failure or observation.get("error_type") or observed_status
        elif name == "facts_state":
            details = {"errors": facts_errors}
            if facts_errors:
                behavior, failure = "fail", "facts_or_state_mismatch"
        elif invalid:
            behavior, failure = "fail", "context_integrity_failure"
            details = {"invalid_context_ids": invalid}
        else:
            details = semantic or default_details
            if (
                name == "grounding"
                and semantic
                and any(c["verdict"] in {"unsupported", "contradicted"} for c in semantic["claims"])
            ):
                behavior, failure = "fail", "unsupported_business_claim"
            elif name == "grounding" and semantic and semantic["invalid_output_citations"]:
                behavior, failure = "fail", "unknown_output_citation"
            elif semantic is None or not semantic["claims_complete"]:
                behavior = "needs_review"
            elif name == "answer_content":
                required = {f["facet_id"] for f in required_answerable(turn)}
                if (
                    not required <= set(semantic["answered_required_facets"])
                    or not semantic["action_appropriate"]
                    or (turn["answerability"] != "answerable" and not semantic["gap_disclosed"])
                ):
                    behavior, failure = "fail", "answer_scope_or_omission"
            elif name == "clarification" and not semantic["clarification_appropriate"]:
                behavior, failure = "fail", "unnecessary_or_missing_clarification"
        rows.append(
            {
                **{
                    field: observation[field]
                    for field in (
                        "protocol_id",
                        "mode",
                        "case_id",
                        "probe_id",
                        "turn_id",
                        "trial_id",
                    )
                },
                "assertion_id": name,
                "execution_status": status,
                "behavior_status": behavior,
                "failure_type": failure,
                "severity": "critical" if name == "grounding" else "major",
                "mandatory": True,
                "manual_review": name in {"answer_content", "grounding", "clarification"},
                "observation_hash": content_hash(observation),
                "details": details,
            }
        )
    return rows


def evaluate_assertions(
    dataset: dict[str, Any], observations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    lookup = {
        (c["case_id"], t["turn_id"]): (t, dataset["snapshots"][c["snapshot_id"]])
        for c in dataset["cases"]
        for t in c["turns"]
    }
    rows = []
    for obs in observations:
        turn, snapshot = lookup[(obs["case_id"], obs["turn_id"])]
        rows.extend(score_observation(turn, snapshot, obs))
    return rows
