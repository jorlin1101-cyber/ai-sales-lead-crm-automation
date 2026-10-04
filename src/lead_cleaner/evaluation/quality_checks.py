"""Deterministic quality checks; no product calls, model judges, or report mutation."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any


_BUSINESS_REJECTIONS = frozenset(
    {
        "duplicate_slot_update",
        "unsupported_fact_evidence",
        "invalid_slot_value",
        "unsupported_answer_evidence",
        "unplanned_followup",
        "unsupported_numeric_claim",
        "answer_too_long",
        "invalid_structured_output",
    }
)
_PATHS = ("raw_query", "runtime_rule_query", "runtime_fused_query")
_HIGHER_METRICS = (
    "direct_top_1_hit",
    "direct_top_3_hit",
    "reciprocal_rank_at_3",
    "ndcg_at_3",
    "facet_recall_at_3",
)


class _MissingStage(LookupError):
    pass


def observation_digest(observation: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        observation, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _detail(identifier: str, passed: bool, actual: Any, expected: Any) -> dict[str, Any]:
    return {
        "assertion_id": identifier,
        "pass": bool(passed),
        "actual": actual,
        "expected": expected,
    }


def legacy_conversation_checks(
    case: Mapping[str, Any], response: Mapping[str, Any], *, profile: str = "rule_only"
) -> list[dict[str, Any]]:
    """Share the original four cases' checks, preserving their rule-only contract.

    Live output is not required to reproduce template wording or generation method.
    The caller must additionally arrange human review of its open-ended content.
    """
    if profile not in {"rule_only", "mocked_model", "live"}:
        raise ValueError("Unknown conversation grading profile")
    reply = response["reply_draft"]
    checks = []
    if profile == "rule_only":
        for index, text in enumerate(case["expected_body_contains"]):
            checks.append(
                _detail(f"body_{index}", text in reply["body_text"], reply["body_text"], text)
            )
    # Deliberately retain the old test's historical non-conflicted filter.
    facts = {
        fact["key"]: fact["value"]
        for fact in response["confirmed_facts"]
        if fact["status"] != "conflicted"
    }
    for key, value in case["expected_facts"].items():
        checks.append(_detail(f"fact_{key}", facts.get(key) == value, facts.get(key), value))
        if profile == "live":
            current = [item for item in response["confirmed_facts"] if item["key"] == key]
            checks.append(
                _detail(
                    f"fact_status_{key}",
                    len(current) == 1
                    and current[0]["status"] in {"customer_confirmed", "human_confirmed"},
                    [item["status"] for item in current],
                    ["customer_confirmed", "human_confirmed"],
                )
            )
    checks.append(
        _detail(
            "intents",
            set(case["expected_intents"]).issubset(reply["answer_intents"]),
            reply["answer_intents"],
            case["expected_intents"],
        )
    )
    if case["requires_grounding"]:
        if profile == "rule_only":
            checks.append(
                _detail(
                    "template_method",
                    reply["generation_method"] == "rag_grounded_template",
                    reply["generation_method"],
                    "rag_grounded_template",
                )
            )
        source_ids = reply["source_ids"]
        retrieval_ids = {source["chunk_id"] for source in response["retrieval"]["sources"]}
        checks.extend(
            [
                _detail("sources_present", bool(source_ids), source_ids, "nonempty"),
                _detail(
                    "sources_known",
                    set(source_ids).issubset(retrieval_ids),
                    source_ids,
                    sorted(retrieval_ids),
                ),
            ]
        )
    return checks


def recommendation_contract_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate only the existing 12-case data contract, never model answer quality."""
    cases = payload["cases"]
    checks = [
        _detail(
            "schema",
            payload["schema_version"] == "grounded-recommendation-eval-v1",
            payload["schema_version"],
            "grounded-recommendation-eval-v1",
        ),
        _detail("case_count", len(cases) == 12, len(cases), 12),
        _detail(
            "unique_case_ids",
            len({case["case_id"] for case in cases}) == len(cases),
            [case["case_id"] for case in cases],
            "unique",
        ),
        _detail(
            "languages",
            {"en", "zh", "mixed"} <= {case["language"] for case in cases},
            sorted({case["language"] for case in cases}),
            ["en", "mixed", "zh"],
        ),
    ]
    for case in cases:
        identifier = case["case_id"]
        chunks = case["retrieved_chunks"]
        chunk_ids = [chunk["chunk_id"] for chunk in chunks]
        expected = case["expected"]
        case_checks = {
            "id_prefix": identifier.startswith("gr-"),
            "message": bool(case["lead_message"].strip()),
            "chunk_count": 1 <= len(chunks) <= 3,
            "unique_chunks": len(chunk_ids) == len(set(chunk_ids)),
            "chunk_text": all(chunk["text"].strip() for chunk in chunks),
            "required_behaviors": bool(expected["required_behaviors"]),
            "forbidden_behaviors": bool(expected["forbidden_behaviors"]),
            "citations": set(expected["allowed_citation_ids"]) == set(chunk_ids),
        }
        checks.extend(
            _detail(f"{identifier}:{name}", passed, passed, True)
            for name, passed in case_checks.items()
        )
    forbidden = {behavior for case in cases for behavior in case["expected"]["forbidden_behaviors"]}
    for name in (
        "follow_embedded_instruction",
        "cite_unknown_chunk",
        "invent_exact_price",
        "guarantee_availability",
        "claim_email_sent",
    ):
        checks.append(_detail(f"boundary:{name}", name in forbidden, name in forbidden, True))
    return {
        "schema_version": "recommendation-contract-report-v1",
        "kind": "data_contract",
        "case_count": len(cases),
        "status": "pass" if all(check["pass"] for check in checks) else "fail",
        "checks": checks,
    }


def _retrieval_cases(report: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    if report["report_schema_version"] != "rag-eval-v4":
        raise ValueError("Expected rag-eval-v4")
    if report["label_contract_version"] != "paired-graded-relevance-v2":
        raise ValueError("Unknown retrieval label contract")
    evaluations = report["evaluations"]
    if set(evaluations) != set(_PATHS):
        raise ValueError("Retrieval path set is incomplete or unknown")
    cases_by_key = {}
    query_ids = None
    for path in _PATHS:
        evaluation = evaluations[path]
        if evaluation["path_name"] != path:
            raise ValueError("Retrieval path name does not match its key")
        ids = [case["query_id"] for case in evaluation["cases"]]
        if len(ids) != len(set(ids)) or len(ids) != report["dataset"]["eval_case_count"]:
            raise ValueError("Duplicate or missing retrieval queries")
        if query_ids is not None and set(ids) != query_ids:
            raise ValueError("Retrieval paths contain different queries")
        query_ids = set(ids)
        for case in evaluation["cases"]:
            for metric in _HIGHER_METRICS + ("unjudged_rate_at_3",):
                value = case[metric]
                if metric.startswith("direct_"):
                    if type(value) is not bool:
                        raise ValueError("Retrieval hit metric must be boolean")
                elif (
                    type(value) not in {int, float}
                    or not math.isfinite(value)
                    or not 0 <= value <= 1
                ):
                    raise ValueError("Invalid retrieval metric")
            cases_by_key[(path, case["query_id"])] = case
    return cases_by_key


def compare_retrieval_reports(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare existing v4 per-query outputs without recalculating or averaging labels."""
    errors = []
    regressions = []
    try:
        previous = _retrieval_cases(baseline)
        current = _retrieval_cases(candidate)
        for field in (
            "report_schema_version",
            "label_contract_version",
            "retrieval_pipeline_version",
            "backend",
            "network_access_required",
            "retrieval",
        ):
            if baseline[field] != candidate[field]:
                errors.append(f"changed_{field}")
        for field in ("dataset", "knowledge_snapshot"):
            before = {key: value for key, value in baseline[field].items() if key != "path"}
            after = {key: value for key, value in candidate[field].items() if key != "path"}
            if before != after:
                errors.append(f"changed_{field}")
        if set(previous) != set(current):
            errors.append("changed_query_ids")
        if not errors:
            for (path, query_id), old in previous.items():
                new = current[(path, query_id)]
                if old["input_query"] != new["input_query"]:
                    errors.append(f"changed_input_query:{path}:{query_id}")
                for metric in _HIGHER_METRICS + ("unjudged_rate_at_3",):
                    worse = (
                        new[metric] > old[metric]
                        if metric == "unjudged_rate_at_3"
                        else new[metric] < old[metric]
                    )
                    if worse:
                        regressions.append(
                            {
                                "path": path,
                                "query_id": query_id,
                                "metric": metric,
                                "baseline": old[metric],
                                "candidate": new[metric],
                            }
                        )
    except (KeyError, TypeError, ValueError) as error:
        errors.append(f"invalid_report:{type(error).__name__}")
    return {
        "comparable": not errors,
        "status": "incomparable" if errors else "fail" if regressions else "pass",
        "errors": errors,
        "regressions": [] if errors else regressions,
    }


def _outcome(
    passed: bool, actual: Any, expected: Any, failure_type: str
) -> tuple[str, str | None, Any, Any]:
    return ("pass" if passed else "fail", None if passed else failure_type, actual, expected)


def _rejection(data: Mapping[str, Any]) -> bool:
    if not data.get("rejected", False):
        return False
    if data.get("rejection_code") not in _BUSINESS_REJECTIONS:
        raise ValueError("Unrecognized rejection cannot establish a safe business outcome")
    return True


def _fact_check(
    data: Mapping[str, Any], params: Mapping[str, Any], *, unsafe: bool
) -> tuple[str, str | None, Any, Any]:
    rejected = _rejection(data)
    facts = [fact for fact in data.get("facts", []) if fact["key"] == params["key"]]
    if unsafe:
        if rejected:
            return _outcome(True, {"rejection_code": data["rejection_code"]}, params, "")
        allowed = params.get("allowed_values", [])
        passed = bool(facts) and all(
            (params.get("allow_pending", False) and fact["status"] in {"pending", "conflicted"})
            or (
                fact["status"] in {"customer_confirmed", "human_confirmed"}
                and fact["value"] in allowed
                and fact["value"] != params["forbidden_value"]
            )
            for fact in facts
        )
        return _outcome(passed, facts, params, "unsafe_fact_accepted")
    expected_source = params.get("source_message_id")
    if "source_alias" in params:
        expected_source = data[params["source_alias"]]
        if not expected_source:
            raise ValueError("Expected source alias has no resolved message ID")
    passed = (
        not rejected
        and len(facts) == 1
        and facts[0]["value"] in params.get("allowed_values", [params["value"]])
        and facts[0]["status"] == params["status"]
        and (expected_source is None or facts[0]["source_message_id"] == expected_source)
    )
    return _outcome(passed, facts, params, "fact_mismatch")


def _model_stage(
    observation: Mapping[str, Any], params: Mapping[str, Any]
) -> tuple[str, str | None, Any, Any]:
    selected = [
        stage
        for stage in observation.get("stages", [])
        if stage["stage"] == params["stage"]
        and ("turn" not in params or stage["turn"] == params["turn"])
    ]
    if not selected:
        raise _MissingStage("Expected model stage was not observed")
    expected = params.get("expected_to_run", True)
    if not expected:
        return _outcome(
            all(stage["call_count"] == 0 for stage in selected),
            selected,
            params,
            "unexpected_model_call",
        )
    if any(stage["provider_execution"] == "error" for stage in selected):
        raise RuntimeError("model_provider_error")
    if any(
        stage["provider_execution"] == "not_called" or stage["call_count"] == 0
        for stage in selected
    ):
        raise _MissingStage("Required model stage did not run")
    return _outcome(
        all(
            stage["expected_to_run"]
            and stage["provider_execution"] == "succeeded"
            and stage["validation_result"] == "accepted"
            and not stage["fallback_used"]
            for stage in selected
        ),
        selected,
        params,
        "model_candidate_rejected",
    )


def _check(
    check: str, params: Mapping[str, Any], observation: Mapping[str, Any], mode: str
) -> tuple[str, str | None, Any, Any]:
    data = observation["data"]
    if check in {"fact", "unsafe_fact"}:
        return _fact_check(data, params, unsafe=check == "unsafe_fact")
    if check == "model_stage":
        return _model_stage(observation, params)
    if check == "conversation_legacy":
        case = params.get("case", params)
        checks = legacy_conversation_checks(case, data["response"], profile=mode)
        if not all(item["pass"] for item in checks):
            return "fail", "conversation_mismatch", checks, case
        return ("needs_review" if mode == "live" else "pass"), None, checks, case
    if check == "claim_guard":
        rejected = _rejection(data)
        body = (data.get("reply") or {}).get("body_text", "")
        retained = [text for text in params["forbidden_text"] if text in body]
        passed = not retained and (rejected or bool(body.strip()))
        return _outcome(
            passed,
            {"retained": retained, "body_text": body, "rejected": rejected},
            params,
            "unsupported_claim_accepted",
        )
    if check == "reply_grounding":
        rejected = _rejection(data)
        reply = data.get("reply") or {}
        body = reply.get("body_text", "")
        sources = reply.get("source_ids", [])
        expected_sources = params["expected_source_ids"]
        passed = (
            not rejected
            and bool(body.strip())
            and bool(sources)
            and set(sources) == set(expected_sources)
            and (mode == "live" or all(text in body for text in params.get("expected_text", [])))
        )
        result = _outcome(passed, reply, params, "grounded_reply_mismatch")
        if passed and mode == "live":
            return "needs_review", None, reply, params
        return result
    if check == "persistence_consistency":
        if data.get("query_executed") is not True:
            raise ValueError("Persistence verification requires an actual database query")
        comparison = data["api_comparison"]
        fields = ("facts_match", "draft_match", "source_links_valid")
        return _outcome(
            all(comparison[field] is True for field in fields),
            comparison,
            {field: True for field in fields},
            "persistence_mismatch",
        )
    if check == "feature":
        features = data["features"]
        return _outcome(
            features.get(params["field"]) == params["value"],
            features.get(params["field"]),
            params["value"],
            "feature_mismatch",
        )
    if check == "not_opted_out":
        response = data.get("response", {})
        state = response.get("state", data.get("state"))
        if state is None:
            raise ValueError("Missing observed conversation state")
        return _outcome(state != "do_not_contact", state, "contact_allowed", "false_opt_out")
    raise ValueError(f"Unknown quality check: {check}")


def evaluate_assertions(
    cases: Sequence[Mapping[str, Any]],
    observations: Sequence[Mapping[str, Any]],
    *,
    mode: str,
    trials: int,
) -> list[dict[str, Any]]:
    """Expand all expected checks, preserving missing and failed observations."""
    if mode not in {"rule_only", "mocked_model", "live"} or trials < 1:
        raise ValueError("Invalid evaluation mode or trial count")
    index = {}
    for observed_entry in observations:
        key = tuple(
            observed_entry[name]
            for name in ("mode", "case_id", "probe_id", "checkpoint", "trial_id")
        )
        if key in index:
            raise ValueError("Duplicate observation key")
        index[key] = observed_entry
    results = []
    result_keys = set()
    for case in cases:
        if mode not in case.get("applicable_modes", [mode]):
            continue
        case_id = case["case_id"]
        for trial in range(1, trials + 1):
            for spec in case["assertions"]:
                if mode not in spec.get("applicable_modes", [mode]):
                    continue
                key = (
                    mode,
                    case_id,
                    spec.get("probe_id", "main"),
                    spec.get("checkpoint", "result"),
                    str(trial),
                )
                unique = (*key, spec["assertion_id"])
                if unique in result_keys:
                    raise ValueError("Duplicate assertion key")
                result_keys.add(unique)
                observation = index.get(key)
                result = {
                    "mode": mode,
                    "case_id": case_id,
                    "probe_id": key[2],
                    "checkpoint": key[3],
                    "assertion_id": spec["assertion_id"],
                    "trial_id": str(trial),
                    "execution_status": "not_run",
                    "behavior_status": None,
                    "mandatory": spec.get("mandatory", True),
                    "severity": spec.get("severity", "critical"),
                    "manual_review": spec.get("manual_review", False),
                    "failure_type": "missing_observation",
                    "known_issue_id": None,
                    "actual": None,
                    "expected": spec.get("params", {}),
                    "observation_hash": None,
                }
                if observation is None:
                    results.append(result)
                    continue
                result["observation_hash"] = observation_digest(observation)
                status = observation["execution_status"]
                result["execution_status"] = status
                result["actual"] = observation["data"]
                if status != "completed":
                    result["failure_type"] = observation.get("error_type") or status
                    # Applicability comes from the frozen spec, never a runtime excuse.
                    if status == "not_applicable":
                        result["execution_status"] = "error"
                        result["failure_type"] = "unexpected_not_applicable"
                    results.append(result)
                    continue
                try:
                    behavior, failure, actual, expected = _check(
                        spec["check"], spec.get("params", {}), observation, mode
                    )
                    result.update(
                        behavior_status=behavior,
                        failure_type=failure,
                        actual=actual,
                        expected=expected,
                    )
                except _MissingStage:
                    result.update(execution_status="not_run", failure_type="missing_model_stage")
                except RuntimeError:
                    result.update(execution_status="error", failure_type="model_provider_error")
                except (KeyError, TypeError, ValueError, AttributeError):
                    result.update(execution_status="error", failure_type="checker_error")
                results.append(result)
    return results
