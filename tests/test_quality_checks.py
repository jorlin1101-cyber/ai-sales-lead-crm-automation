from copy import deepcopy
import json
from pathlib import Path

import pytest

from lead_cleaner.evaluation.quality_checks import (
    compare_retrieval_reports,
    evaluate_assertions,
    legacy_conversation_checks,
    observation_digest,
    recommendation_contract_report,
)
from lead_cleaner.rag.evaluation_report import run_keyword_evaluation


def observation(data=None, *, mode="mocked_model", stages=None, **changes):
    result = {
        "mode": mode,
        "case_id": "selfcheck",
        "probe_id": "main",
        "checkpoint": "result",
        "trial_id": "1",
        "execution_status": "completed",
        "data": data or {},
        "stages": stages or [],
        "error_type": None,
    }
    result.update(changes)
    return result


def evaluate(check, params, data=None, *, mode="mocked_model", stages=None, **changes):
    case = {
        "case_id": "selfcheck",
        "assertions": [
            {
                "assertion_id": "target",
                "check": check,
                "params": params,
                "manual_review": mode == "live",
            }
        ],
    }
    observed = observation(data, mode=mode, stages=stages, **changes)
    return evaluate_assertions([case], [observed], mode=mode, trials=1)[0]


def fact(value="8", status="customer_confirmed", source="m1"):
    return {
        "key": "group_size",
        "value": value,
        "status": status,
        "source_message_id": source,
    }


@pytest.mark.parametrize(
    "value,status,source,expected",
    [
        ("8", "customer_confirmed", "m1", "pass"),
        ("999", "customer_confirmed", "m1", "fail"),
        ("8", "inferred", "m1", "fail"),
        ("8", "pending", "m1", "fail"),
        ("8", "customer_confirmed", "old", "fail"),
    ],
)
def test_fact_checks_value_confirmation_and_resolved_source(value, status, source, expected):
    result = evaluate(
        "fact",
        {
            "key": "group_size",
            "value": "8",
            "status": "customer_confirmed",
            "source_alias": "current_message_id",
        },
        {"facts": [fact(value, status, source)], "current_message_id": "m1"},
    )
    assert result["behavior_status"] == expected
    assert result["execution_status"] == "completed"


@pytest.mark.parametrize(
    "facts,rejected,code,expected,status",
    [
        ([fact("999")], False, None, "fail", "completed"),
        ([fact("7")], False, None, "fail", "completed"),
        ([fact("8")], False, None, "pass", "completed"),
        ([fact("undecided", "pending")], False, None, "pass", "completed"),
        ([], True, "unsupported_fact_evidence", "pass", "completed"),
        ([], True, "provider_error", None, "error"),
        ([], False, None, "fail", "completed"),
    ],
)
def test_unsafe_fact_requires_supported_value_pending_or_real_business_rejection(
    facts, rejected, code, expected, status
):
    result = evaluate(
        "unsafe_fact",
        {
            "key": "group_size",
            "forbidden_value": "999",
            "allowed_values": ["8"],
            "allow_pending": True,
        },
        {"facts": facts, "rejected": rejected, "rejection_code": code},
    )
    assert (result["behavior_status"], result["execution_status"]) == (expected, status)


@pytest.mark.parametrize(
    "data,expected",
    [
        (
            {"reply": {"body_text": "Booking confirmed", "generation_method": "context_template"}},
            "fail",
        ),
        ({"reply": {"body_text": "Please wait for the adviser to verify availability."}}, "pass"),
        ({"rejected": True, "rejection_code": "unsupported_answer_evidence"}, "pass"),
        ({"reply": {"body_text": ""}}, "fail"),
    ],
)
def test_claim_selfcheck_preserves_bad_content_even_if_flags_change(data, expected):
    result = evaluate("claim_guard", {"forbidden_text": ["Booking confirmed"]}, data)
    assert result["behavior_status"] == expected


@pytest.mark.parametrize("error_type", ["timeout", "database_error", "http_500"])
def test_infrastructure_failure_never_counts_as_safety_interception(error_type):
    result = evaluate(
        "claim_guard",
        {"forbidden_text": ["Booking confirmed"]},
        execution_status="error",
        error_type=error_type,
    )
    assert result["behavior_status"] is None
    assert result["execution_status"] == "error"
    assert result["failure_type"] == error_type


@pytest.mark.parametrize(
    "mode,body,sources,expected",
    [
        ("mocked_model", "Hotels affect pricing.", ["c1"], "pass"),
        ("mocked_model", "Unrelated.", ["c1"], "fail"),
        ("mocked_model", "Hotels affect pricing.", ["missing"], "fail"),
        ("live", "The cost depends on hotel selection.", ["c1"], "needs_review"),
        ("live", "The cost depends on hotel selection.", ["missing"], "fail"),
    ],
)
def test_grounding_does_not_use_literal_wording_as_live_semantic_judge(
    mode, body, sources, expected
):
    result = evaluate(
        "reply_grounding",
        {"expected_text": ["Hotels"], "expected_source_ids": ["c1"]},
        {"reply": {"body_text": body, "source_ids": sources}},
        mode=mode,
    )
    assert result["behavior_status"] == expected


def legacy_pair():
    case = {
        "expected_body_contains": ["8天7晚"],
        "expected_facts": {"destination": "Western Sichuan"},
        "expected_intents": ["itinerary"],
        "requires_grounding": True,
    }
    response = {
        "confirmed_facts": [
            {"key": "destination", "value": "Western Sichuan", "status": "customer_confirmed"}
        ],
        "reply_draft": {
            "body_text": "8天7晚",
            "answer_intents": ["itinerary"],
            "source_ids": ["c1"],
            "generation_method": "rag_grounded_template",
        },
        "retrieval": {"sources": [{"chunk_id": "c1"}]},
    }
    return case, response


def test_original_rule_profile_keeps_wording_method_and_legacy_fact_filter():
    case, response = legacy_pair()
    response["confirmed_facts"][0]["status"] = "pending"
    assert all(item["pass"] for item in legacy_conversation_checks(case, response))
    response["reply_draft"]["generation_method"] = "llm_grounded"
    checks = legacy_conversation_checks(case, response)
    assert [item["assertion_id"] for item in checks if not item["pass"]] == ["template_method"]
    with pytest.raises(ValueError, match="profile"):
        legacy_conversation_checks(case, response, profile="unknown")


def test_live_conversation_rephrasing_needs_review_not_template_failure():
    case, response = legacy_pair()
    response["reply_draft"].update(
        body_text="Eight days and seven nights.", generation_method="llm_grounded"
    )
    result = evaluate("conversation_legacy", {"case": case}, {"response": response}, mode="live")
    assert result["behavior_status"] == "needs_review"
    response["confirmed_facts"][0]["value"] = "Yunnan"
    result = evaluate("conversation_legacy", case, {"response": response}, mode="live")
    assert result["behavior_status"] == "fail"


def stage(**changes):
    result = {
        "stage": "generation",
        "turn": 1,
        "expected_to_run": True,
        "provider_execution": "succeeded",
        "validation_result": "accepted",
        "call_count": 1,
        "fallback_used": False,
    }
    result.update(changes)
    return result


@pytest.mark.parametrize(
    "stages,execution,behavior",
    [
        ([stage()], "completed", "pass"),
        ([stage(provider_execution="error", fallback_used=True)], "error", None),
        ([stage(provider_execution="not_called", call_count=0)], "not_run", None),
        ([stage(validation_result="rejected", fallback_used=True)], "completed", "fail"),
        ([], "not_run", None),
    ],
)
def test_model_stage_failure_is_independent_of_successful_template(stages, execution, behavior):
    _, response = legacy_pair()
    result = evaluate(
        "model_stage",
        {"stage": "generation", "turn": 1},
        {"response": response},
        mode="live",
        stages=stages,
    )
    assert (result["execution_status"], result["behavior_status"]) == (execution, behavior)


def test_unexpected_model_call_fails_a_predeclared_not_required_stage():
    assert (
        evaluate(
            "model_stage", {"stage": "generation", "expected_to_run": False}, stages=[stage()]
        )["behavior_status"]
        == "fail"
    )
    assert (
        evaluate(
            "model_stage",
            {"stage": "generation", "expected_to_run": False},
            stages=[stage(call_count=0, provider_execution="not_called")],
        )["behavior_status"]
        == "pass"
    )


@pytest.mark.parametrize("matches,expected", [(True, "pass"), (False, "fail")])
def test_persistence_is_checked_from_actual_query_and_all_comparisons(matches, expected):
    data = {
        "query_executed": True,
        "api_comparison": {"facts_match": matches, "draft_match": True, "source_links_valid": True},
    }
    assert evaluate("persistence_consistency", {}, data)["behavior_status"] == expected
    data["query_executed"] = False
    result = evaluate("persistence_consistency", {}, data)
    assert result["execution_status"] == "error"
    assert result["behavior_status"] is None


def test_feature_and_opt_out_checks_expose_wrong_state():
    assert (
        evaluate("feature", {"field": "partner", "value": False}, {"features": {"partner": True}})[
            "behavior_status"
        ]
        == "fail"
    )
    assert (
        evaluate("feature", {"field": "partner", "value": False}, {"features": {"partner": False}})[
            "behavior_status"
        ]
        == "pass"
    )
    assert (
        evaluate("not_opted_out", {}, {"response": {"state": "do_not_contact"}})["behavior_status"]
        == "fail"
    )
    assert evaluate("not_opted_out", {}, {"state": "ready_for_review"})["behavior_status"] == "pass"
    assert evaluate("not_opted_out", {})["execution_status"] == "error"


def test_missing_observations_keep_every_expected_trial_in_denominator():
    cases = [{"case_id": "selfcheck", "assertions": [{"assertion_id": "check", "check": "fact"}]}]
    results = evaluate_assertions(cases, [], mode="live", trials=3)
    assert [item["trial_id"] for item in results] == ["1", "2", "3"]
    assert all(item["execution_status"] == "not_run" for item in results)
    assert all(item["behavior_status"] is None for item in results)
    cases[0]["assertions"][0]["applicable_modes"] = ["rule_only"]
    assert evaluate_assertions(cases, [], mode="live", trials=3) == []
    cases[0]["applicable_modes"] = ["rule_only"]
    assert evaluate_assertions(cases, [], mode="live", trials=3) == []


def test_duplicate_keys_invalid_mode_and_runtime_inapplicability_are_not_silent():
    observed = observation()
    with pytest.raises(ValueError, match="Duplicate observation"):
        evaluate_assertions([], [observed, observed], mode="rule_only", trials=1)
    with pytest.raises(ValueError, match="Invalid"):
        evaluate_assertions([], [], mode="unknown", trials=1)
    spec = {"assertion_id": "target", "check": "fact"}
    cases = [{"case_id": "selfcheck", "assertions": [spec, spec]}]
    with pytest.raises(ValueError, match="Duplicate assertion"):
        evaluate_assertions(cases, [], mode="rule_only", trials=1)
    result = evaluate("fact", {}, execution_status="not_applicable")
    assert (result["execution_status"], result["behavior_status"]) == ("error", None)
    assert evaluate("unknown", {})["execution_status"] == "error"


def test_missing_field_is_checker_error_not_model_stage_missing():
    result = evaluate(
        "fact",
        {
            "key": "group_size",
            "value": "8",
            "status": "customer_confirmed",
            "source_alias": "missing",
        },
        {"facts": [fact()]},
    )
    assert result["execution_status"] == "error"
    assert result["failure_type"] == "checker_error"
    result = evaluate(
        "fact",
        {
            "key": "group_size",
            "value": "8",
            "status": "customer_confirmed",
            "source_alias": "empty",
        },
        {"facts": [fact()], "empty": ""},
    )
    assert result["execution_status"] == "error"


def test_observation_hash_binds_whole_evidence_and_is_stable_across_key_order():
    observed = observation({"message": "中文", "facts": [fact()]})
    assert observation_digest(observed) == observation_digest(
        dict(reversed(list(observed.items())))
    )
    modified = deepcopy(observed)
    modified["data"]["facts"][0]["value"] = "999"
    assert observation_digest(observed) != observation_digest(modified)
    result = evaluate(
        "fact",
        {"key": "group_size", "value": "8", "status": "customer_confirmed"},
        observed["data"],
    )
    assert result["observation_hash"] == observation_digest(observed)


def test_recommendation_report_validates_data_only_and_keeps_all_original_boundaries():
    payload = json.loads(
        Path("data/recommendation_eval/golden_cases.json").read_text(encoding="utf-8")
    )
    report = recommendation_contract_report(payload)
    assert (report["status"], report["kind"], report["case_count"]) == ("pass", "data_contract", 12)
    payload["cases"][0]["expected"]["allowed_citation_ids"] = ["unknown"]
    payload["cases"][1]["lead_message"] = " "
    report = recommendation_contract_report(payload)
    assert report["status"] == "fail"
    assert len([check for check in report["checks"] if not check["pass"]]) == 2
    assert "accuracy" not in report


@pytest.fixture(scope="module")
def retrieval():
    return run_keyword_evaluation(
        chunks_path="data/knowledge_snapshot/knowledge_chunks.json",
        eval_queries_path="data/rag_eval/eval_queries.json",
    )


def test_v4_comparison_ignores_timing_but_keeps_each_query_regression(retrieval):
    candidate = deepcopy(retrieval)
    candidate["generated_at_utc"] = "different"
    candidate["evaluations"]["raw_query"]["latency"]["mean_query_ms"] = 0
    assert compare_retrieval_reports(retrieval, candidate)["status"] == "pass"
    before = candidate["evaluations"]["raw_query"]["cases"][0]
    before["direct_top_1_hit"] = False
    before["reciprocal_rank_at_3"] = 0
    before["unjudged_rate_at_3"] = 1
    report = compare_retrieval_reports(retrieval, candidate)
    assert report["status"] == "fail"
    assert {row["metric"] for row in report["regressions"]} >= {
        "reciprocal_rank_at_3",
        "unjudged_rate_at_3",
    }


@pytest.mark.parametrize(
    "change",
    [
        "schema",
        "labels",
        "dataset",
        "knowledge",
        "config",
        "paths",
        "path_name",
        "duplicate",
        "missing_query",
        "query_ids",
        "input_query",
        "nan",
        "bad_hit",
        "bad_numeric",
        "missing_field",
    ],
)
def test_v4_rejects_incomparable_or_malformed_reports(retrieval, change):
    candidate = deepcopy(retrieval)
    path = candidate["evaluations"]["raw_query"]
    if change == "schema":
        candidate["report_schema_version"] = "v3"
    elif change == "labels":
        candidate["label_contract_version"] = "unknown"
    elif change in {"dataset", "knowledge"}:
        candidate["dataset" if change == "dataset" else "knowledge_snapshot"]["sha256"] = "changed"
    elif change == "config":
        candidate["retrieval"]["rrf_k"] = 1
    elif change == "paths":
        candidate["evaluations"].pop("runtime_fused_query")
    elif change == "path_name":
        path["path_name"] = "unknown"
    elif change == "duplicate":
        path["cases"][1]["query_id"] = path["cases"][0]["query_id"]
    elif change == "missing_query":
        path["cases"].pop()
    elif change == "query_ids":
        for evaluation in candidate["evaluations"].values():
            evaluation["cases"][0]["query_id"] = "new-query"
    elif change == "input_query":
        path["cases"][0]["input_query"] = "different input"
    elif change == "nan":
        path["cases"][0]["ndcg_at_3"] = float("nan")
    elif change == "bad_hit":
        path["cases"][0]["direct_top_1_hit"] = "true"
    elif change == "bad_numeric":
        path["cases"][0]["ndcg_at_3"] = 2
    else:
        path["cases"][0].pop("ndcg_at_3")
    report = compare_retrieval_reports(retrieval, candidate)
    assert report["comparable"] is False
    assert report["status"] == "incomparable"
    assert report["errors"]
    assert report["regressions"] == []


def test_safe_rejection_without_a_draft_is_not_an_execution_error():
    data = {"rejected": True, "rejection_code": "unsupported_answer_evidence", "reply": None}
    result = evaluate("claim_guard", {"forbidden_text": ["Booking confirmed"]}, data)
    assert (result["execution_status"], result["behavior_status"]) == ("completed", "pass")
    result = evaluate(
        "reply_grounding", {"expected_text": ["Hotels"], "expected_source_ids": ["c1"]}, data
    )
    assert (result["execution_status"], result["behavior_status"]) == ("completed", "fail")


@pytest.mark.parametrize(
    "value,status,expected",
    [
        ("人数未定", "pending", "pass"),
        ("待定", "pending", "pass"),
        ("人数未定", "customer_confirmed", "fail"),
        ("999", "pending", "fail"),
    ],
)
def test_pending_facts_accept_only_frozen_equivalent_values_with_pending_status(
    value, status, expected
):
    result = evaluate(
        "fact",
        {
            "key": "group_size",
            "value": "待定",
            "status": "pending",
            "allowed_values": ["待定", "人数未定"],
            "source_alias": "current_message_id",
        },
        {"facts": [fact(value, status)], "current_message_id": "m1"},
        mode="live",
    )
    assert result["behavior_status"] == expected


@pytest.mark.parametrize(
    "status,expected",
    [
        ("pending", "fail"),
        ("inferred", "fail"),
        ("conflicted", "fail"),
        ("customer_confirmed", "needs_review"),
        ("human_confirmed", "needs_review"),
    ],
)
def test_live_legacy_fact_state_is_stricter_than_the_historical_rule_profile(status, expected):
    case, response = legacy_pair()
    response["confirmed_facts"][0]["status"] = status
    response["reply_draft"]["generation_method"] = "llm_grounded"
    result = evaluate("conversation_legacy", case, {"response": response}, mode="live")
    assert result["behavior_status"] == expected
    if expected == "fail":
        failed = [detail["assertion_id"] for detail in result["actual"] if not detail["pass"]]
        assert "fact_status_destination" in failed
