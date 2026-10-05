"""Derive regression judgments from identical, previously human-reviewed evidence.

This never creates human reviews or grants acceptance authority. The regression
caller must retain ordinary execution, known-issue and retrieval gates.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .checks import expected_keys, score_observation
from .reports import (
    FINGERPRINTS,
    OBSERVATION_FIELDS,
    ReportError,
    content_hash,
    key,
    load_run,
    parse_json,
)
from .trust import effective_assertions
from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.conversation import ConversationFact, ConversationTurnResult

ALGORITHM = "semantic-fingerprint.v1"
SEMANTIC_ASSERTIONS = {"answer_content", "grounding", "clarification"}
OBSERVATION_KEYS = {
    "protocol_id",
    "mode",
    "case_id",
    "probe_id",
    "turn_id",
    "trial_id",
    "execution_status",
    "error_type",
    "input_message",
    "history",
    "response",
    "facts",
    "state",
    "reply_text",
    "retrieved_chunks",
    "provided_context",
    "provided_context_rule",
    "provided_context_model",
    "stages",
    "api_status",
    "predicted_answerability",
    "model_calls",
    "retrieval_calls",
    "message_id_map",
    "network_guard",
}
STAGE_KEYS = {
    "stage",
    "applicable",
    "expected_to_run",
    "provider_kind",
    "provider_execution",
    "validation_result",
    "call_count",
    "retry_count",
    "fallback_used",
    "error_type",
    "not_called_reason",
}
# Only explicitly named instrumentation fields can be ignored. A new observer
# field is not silently classified as harmless by a prefix/suffix heuristic.
OPTIONAL_TIMING = {"duration_ms"}


class NonReusableObservation(ValueError):
    """Complete equivalence could not be established; request fresh human review."""


def _require(condition: bool) -> None:
    if not condition:
        raise NonReusableObservation("Observation is not eligible for strict semantic reuse")


def _shape(value: Any, required: set[str], optional: set[str] | None = None) -> None:
    _require(isinstance(value, dict) and required <= set(value) <= required | (optional or set()))


def _timing(value: dict[str, Any]) -> None:
    if "duration_ms" in value:
        duration = value.pop("duration_ms")
        _require(type(duration) in {int, float} and 0 <= duration < float("inf"))


def _facts(values: Any, inverse: dict[str, str]) -> list[dict[str, Any]]:
    _require(isinstance(values, list))
    result = []
    for fact in values:
        _require(ConversationFact.model_validate(fact).model_dump(mode="json") == fact)
        _require(fact["source_message_id"] in inverse)
        result.append({**fact, "source_message_id": inverse[fact["source_message_id"]]})
    return result


def semantic_fingerprint(
    run: dict[str, Any], observation: dict[str, Any], dataset: dict[str, Any]
) -> str:
    """Hash all recorded business evidence after path-specific ID normalization."""
    value = deepcopy(observation)
    _shape(value, OBSERVATION_KEYS, OPTIONAL_TIMING | {"request_id"})
    _timing(value)
    if "request_id" in value:
        _require(isinstance(value.pop("request_id"), str))
    _require(
        value["execution_status"] == "completed"
        and value["error_type"] is None
        and value["api_status"] == 200
    )
    _require(value["predicted_answerability"] is None)
    metadata = run["metadata"]
    _require(value["mode"] == metadata["mode"] and value["protocol_id"] == metadata["protocol_id"])
    case = next(c for c in dataset["cases"] if c["case_id"] == value["case_id"])
    index = next(i for i, turn in enumerate(case["turns"]) if turn["turn_id"] == value["turn_id"])
    turn = case["turns"][index]
    _require(value["input_message"] == turn["message"])
    _require(
        isinstance(value["history"], list) and all(isinstance(h, str) for h in value["history"])
    )
    mapping = value["message_id_map"]
    _require(
        isinstance(mapping, dict)
        and set(mapping) == {t["turn_id"] for t in case["turns"][: index + 1]}
    )
    _require(all(isinstance(identifier, str) and identifier for identifier in mapping.values()))
    _require(len(set(mapping.values())) == len(mapping))
    inverse = {identifier: identifier_turn for identifier_turn, identifier in mapping.items()}
    value["message_id_map"] = {identifier_turn: identifier_turn for identifier_turn in mapping}
    response = value["response"]
    _require(ConversationTurnResult.model_validate(response).model_dump(mode="json") == response)
    _require(value["facts"] == response["confirmed_facts"] and value["state"] == response["state"])
    draft = response["reply_draft"]
    _require(value["reply_text"] == draft["body_text"] and bool(value["reply_text"]))
    _require(response["turn_number"] == draft["turn_number"] == index + 1)
    conversation = response["conversation_id"]
    lead = response["current_analysis"]["cleaned_lead"]
    _require(draft["conversation_id"] == conversation == lead["external_lead_id"])
    _require(
        lead["lead_id"] == str(uuid5(NAMESPACE_URL, f"{lead['source'].casefold()}:{conversation}"))
    )
    del response["conversation_id"], draft["conversation_id"], draft["draft_id"]
    del lead["lead_id"], lead["external_lead_id"]
    del response["current_analysis"]["analysis_id"]
    value["facts"] = _facts(value["facts"], inverse)
    response["confirmed_facts"] = _facts(response["confirmed_facts"], inverse)
    for field in (
        "retrieved_chunks",
        "provided_context",
        "provided_context_rule",
        "provided_context_model",
    ):
        _require(isinstance(value[field], list))
        for chunk in value[field]:
            _require(RetrievedChunk.model_validate(chunk).model_dump(mode="json") == chunk)
    selected = (
        "provided_context_model"
        if draft["generation_method"] == "llm_grounded"
        else "provided_context_rule"
    )
    _require(value["provided_context"] == value[selected])
    stages = value["stages"]
    _require(
        isinstance(stages, list)
        and [s.get("stage") for s in stages] == ["understanding", "generation"]
    )
    expected_calls = []
    for stage in stages:
        _shape(stage, STAGE_KEYS, OPTIONAL_TIMING)
        _timing(stage)
        _require(
            stage["error_type"] is None
            and stage["fallback_used"] is False
            and stage["retry_count"] == 0
        )
        _require(type(stage["expected_to_run"]) is bool and type(stage["call_count"]) is int)
        mocked = value["mode"] == "mocked_model"
        _require(
            stage["applicable"] is mocked
            and stage["provider_kind"] == ("mock" if mocked else "none")
        )
        if stage["expected_to_run"]:
            _require(
                mocked
                and stage["call_count"] >= 1
                and stage["provider_execution"] == "succeeded"
                and stage["validation_result"] == "accepted"
            )
            expected_calls.extend([stage["stage"]] * stage["call_count"])
        else:
            _require(
                stage["call_count"] == 0
                and stage["provider_execution"] == "not_called"
                and stage["validation_result"] == "not_reached"
                and bool(stage["not_called_reason"])
            )
    _require(
        isinstance(value["model_calls"], list) and len(value["model_calls"]) == len(expected_calls)
    )
    for call, name in zip(value["model_calls"], expected_calls, strict=True):
        _shape(call, {"request", "response", "provider_execution"}, OPTIONAL_TIMING)
        _timing(call)
        _require(call["provider_execution"] == "succeeded")
        request = call["request"]
        _shape(
            request,
            {"model", "messages", "response_format", "extra_body", "max_tokens", "temperature"},
        )
        messages = request["messages"]
        _require(isinstance(messages, list) and len(messages) == 2)
        for message, role in zip(messages, ("system", "user"), strict=True):
            _shape(message, {"role", "content"})
            _require(message["role"] == role and isinstance(message["content"], str))
        payload = parse_json(messages[1]["content"])
        fields = (
            {
                "current_message",
                "existing_facts",
                "pending_questions",
                "recent_customer_and_recorded_sent_history",
            }
            if name == "understanding"
            else {
                "current_message",
                "language",
                "channel",
                "current_facts",
                "recommended_products",
                "reply_intents",
                "evidence",
            }
        )
        _shape(payload, fields)
        _require(payload["current_message"] == value["input_message"])
        fact_field = "existing_facts" if name == "understanding" else "current_facts"
        payload[fact_field] = _facts(payload[fact_field], inverse)
        if name == "understanding":
            _require(payload["recent_customer_and_recorded_sent_history"] == value["history"][-6:])
        # Preserve parsed JSON values exactly, only replacing actual source IDs.
        messages[1]["content"] = payload
    for call in value["retrieval_calls"]:
        fields = {"method", "query", "results", "error_type"}
        if call.get("method") == "retrieve":
            fields.add("retrieval_method")
        _shape(call, fields, OPTIONAL_TIMING)
        _timing(call)
        _require(call["method"] in {"retrieve", "product_manuals"} and call["error_type"] is None)
        _require(call.get("retrieval_method") not in {"unavailable", "disabled"})
        for chunk in call["results"]:
            _require(RetrievedChunk.model_validate(chunk).model_dump(mode="json") == chunk)
    guard = value["network_guard"]
    _shape(guard, {"external_blocked", "loopback_connections", "target_connections", "target_host"})
    _require(
        guard["external_blocked"] == guard["target_connections"] == 0
        and guard["target_host"] is None
    )
    _require(type(guard["loopback_connections"]) is int and guard["loopback_connections"] >= 0)
    del guard["loopback_connections"]
    frozen = {
        field: metadata[field] for field in (*FINGERPRINTS, "rubric_hash", "review_required_roles")
    }
    return content_hash(
        {"algorithm": ALGORITHM, "frozen": frozen, "turn": turn, "observation": value}
    )


def _fresh(run: dict[str, Any]) -> dict[str, Any]:
    fresh = load_run(run["directory"])
    if fresh["manifest_hash"] != run["manifest_hash"]:
        raise ReportError("Semantic reuse requires the original sealed report")
    return fresh


def _automatic_compatible(
    rows: list[dict[str, Any]], raw: dict, previous: dict, record: dict
) -> bool:
    if {row["assertion_id"] for row in rows} != {"execution", "facts_state"}:
        return False
    signature = ("execution_status", "behavior_status", "failure_type", "severity")
    issue_fields = (
        "protocol_id",
        "mode",
        "case_id",
        "probe_id",
        "turn_id",
        "assertion_id",
        "failure_type",
        "severity",
    )
    for row in rows:
        identity = key(row)
        original, old = raw[identity], previous[identity]
        if row["execution_status"] != "completed" or any(
            row.get(f) != original.get(f) for f in signature
        ):
            return False
        if row["behavior_status"] == old["behavior_status"] == "pass":
            continue
        # An approved, unchanged historical fact failure may coexist with an
        # independent semantic judgment. Never change or exempt that auto row.
        if (
            row["assertion_id"] != "facts_state"
            or row["behavior_status"] != "fail"
            or any(row.get(f) != old.get(f) for f in signature)
        ):
            return False
        issues = record.get("known_issues", [])
        if record.get("known_issues_hash") != content_hash(issues) or not any(
            issue.get("status") == "open" and all(issue.get(f) == row.get(f) for f in issue_fields)
            for issue in issues
        ):
            return False
    return True


def reuse_reviewed_assertions(
    baseline_run: dict[str, Any],
    baseline_record: dict[str, Any],
    candidate_run: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
    trust: dict[str, Any],
    dataset: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Regression-only helper; equivalent evidence is derived, never re-reviewed."""
    baseline, candidate = _fresh(baseline_run), _fresh(candidate_run)
    rows = deepcopy(candidate_rows)
    mode = candidate["metadata"]["mode"]
    acceptance = baseline_record.get("acceptance_id")
    if (
        not acceptance
        or trust.get("latest_accepted_baselines", {}).get(mode) != acceptance
        or trust.get("accepted_baselines", {}).get(acceptance) != baseline["manifest_hash"]
        or baseline_record.get("manifest_hash") != baseline["manifest_hash"]
    ):
        raise ReportError("Semantic reuse requires the latest independently accepted baseline")
    fields = (
        *FINGERPRINTS,
        "rubric_hash",
        "expected_keys",
        "expected_retrieval_keys",
        "review_required_roles",
    )
    if any(baseline["metadata"].get(field) != candidate["metadata"].get(field) for field in fields):
        raise ReportError("Semantic reuse cannot cross frozen protocol inputs")
    if any(
        candidate["metadata"].get(field) != dataset.get(field)
        for field in ("dataset_hash", "knowledge_hash")
    ) or candidate["metadata"]["expected_keys"] != expected_keys(dataset, mode):
        raise ReportError("Semantic reuse requires the independently loaded matching dataset")
    if [key(row) for row in rows] != [key(row) for row in candidate["assertions"]]:
        raise ReportError("Candidate effective assertion identities differ")
    source_rows, digest, _ = effective_assertions(
        baseline, baseline_record.get("review_set"), trust, dataset=dataset
    )
    if baseline_record.get("review_set_hash") != digest:
        raise ReportError("Baseline review set differs from its accepted binding")
    source = {key(row): row for row in source_rows}
    source_raw = {key(row): row for row in baseline["assertions"]}
    candidate_raw = {key(row): row for row in candidate["assertions"]}
    observations = {key(o, OBSERVATION_FIELDS): o for o in candidate["observations"]}
    previous = {key(o, OBSERVATION_FIELDS): o for o in baseline["observations"]}
    reviews = {r["review_id"]: r for r in baseline_record["review_set"]["reviews"]}
    derived = []
    for row in rows:
        identity = key(row)
        raw, old = candidate_raw[identity], source[identity]
        if (
            row["assertion_id"] not in SEMANTIC_ASSERTIONS
            or row["behavior_status"] != "needs_review"
            or row.get("review_ids")
            or row.get("derived_from")
            or raw["behavior_status"] != "needs_review"
            or source_raw[identity]["behavior_status"] != "needs_review"
            or old["behavior_status"] not in {"pass", "fail"}
            or not old.get("review_ids")
        ):
            continue
        observation_key = key(row, OBSERVATION_FIELDS)
        automatic = [
            r
            for r in rows
            if key(r, OBSERVATION_FIELDS) == observation_key
            and r["assertion_id"] not in SEMANTIC_ASSERTIONS
        ]
        if not _automatic_compatible(automatic, candidate_raw, source, baseline_record):
            continue
        observation, prior = observations[observation_key], previous[observation_key]
        try:
            fingerprint = semantic_fingerprint(candidate, observation, dataset)
            if fingerprint != semantic_fingerprint(baseline, prior, dataset):
                continue
            semantic = deepcopy(reviews[old["review_ids"][0]]["semantic"])
            semantic["observation_hash"] = content_hash(observation)
            case = next(c for c in dataset["cases"] if c["case_id"] == row["case_id"])
            turn = next(t for t in case["turns"] if t["turn_id"] == row["turn_id"])
            computed = next(
                r
                for r in score_observation(
                    turn, dataset["snapshots"][case["snapshot_id"]], observation, semantic
                )
                if r["assertion_id"] == row["assertion_id"]
            )
            if (computed["behavior_status"], computed["failure_type"]) != (
                old["behavior_status"],
                old["failure_type"],
            ):
                continue
        except (ValueError, KeyError, TypeError, StopIteration):
            # Absence of proof is not a proof of equality, nor a tool success.
            continue
        record = {
            "algorithm": ALGORITHM,
            "key": list(identity),
            "semantic_fingerprint": fingerprint,
            "source_acceptance_id": acceptance,
            "source_review_set_hash": digest,
            "source_review_ids": list(old["review_ids"]),
            "source_manifest_hash": baseline["manifest_hash"],
            "source_observation_hash": content_hash(prior),
            "candidate_manifest_hash": candidate["manifest_hash"],
            "candidate_observation_hash": content_hash(observation),
            "verdict": computed["behavior_status"],
            "failure_type": computed["failure_type"],
            "origin": "derived_regression_judgment",
        }
        row.clear()
        row.update(computed, derived_from=deepcopy(record))
        derived.append(record)
    return rows, derived
