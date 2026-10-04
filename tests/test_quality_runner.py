"""Exercise the runner using production boundaries and isolated local databases."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from openai import APITimeoutError
from unittest.mock import Mock

from lead_cleaner.evaluation._quality_adapters import understanding_data
from lead_cleaner.evaluation._quality_runtime import (
    QualityConfigurationError,
    QueueClient,
    RecordedClient,
    RequestBudget,
    isolated_settings,
)
from lead_cleaner.evaluation.quality_checks import evaluate_assertions
from lead_cleaner.evaluation.quality_runner import load_cases, run_quality_suite
from lead_cleaner.services.conversation_llm import QwenConversationLLM

ROOT = Path(__file__).resolve().parents[1]


def cases(*ids):
    return [case for case in load_cases(ROOT) if case["case_id"] in ids]


def successful_live_factory(created):
    def factory(case, trial, probe):
        def answer(**kwargs):
            payload = json.loads(kwargs["messages"][-1]["content"])
            if "evidence" in payload:
                evidence = payload["evidence"][0]
                return {
                    "paragraphs": [
                        {"evidence_id": evidence["evidence_id"], "text": evidence["quote"]}
                    ]
                }
            return deepcopy(case["payload"].get("mock_response", {"updates": []}))

        client = QueueClient([answer] * 4)
        created.append((case["case_id"], trial, probe, client))
        return client

    return factory


@pytest.fixture(scope="module")
def offline_runs():
    return {
        mode: run_quality_suite(mode, project_root=ROOT) for mode in ("rule_only", "mocked_model")
    }


def test_case_inventory_reuses_four_original_ids_and_has_fixed_mode_counts():
    values = load_cases(ROOT)
    old = [
        json.loads(line)["id"]
        for line in (ROOT / "data/evals/multi_turn_conversations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [case["case_id"] for case in values[:4]] == old
    assert len(values) == len({case["case_id"] for case in values}) == 22
    assert {
        mode: sum(mode in c["applicable_modes"] for c in values)
        for mode in ("rule_only", "mocked_model", "live")
    } == {"rule_only": 10, "mocked_model": 12, "live": 10}
    assert all(case["review_status"] == "draft" for case in values)


def test_production_rule_path_reports_retraction_gap_without_fixing_it(offline_runs):
    result = offline_runs["rule_only"]
    by_id = {o["case_id"]: o for o in result["observations"]}
    assert all(o["execution_status"] == "completed" for o in by_id.values())
    assert by_id["M01"]["data"]["features"]["requests_partnership"] is True
    assert by_id["M01"]["data"]["interface_has_retraction_signal"] is False
    assert by_id["M02"]["data"]["features"]["requests_private_or_custom_service"] is True
    assert by_id["M03"]["data"]["features"]["customer_kind"] == "agency"
    assert by_id["M04"]["data"]["features"]["requests_partnership"] is True
    assert by_id["M06"]["data"]["state"] != "do_not_contact"
    assert result["metadata"]["real_model_calls"] == 0


def test_mocked_wrong_outputs_reach_real_api_and_independent_database(offline_runs):
    result = offline_runs["mocked_model"]
    assert all(o["execution_status"] == "completed" for o in result["observations"])
    found = {(o["case_id"], o["probe_id"], o["checkpoint"]): o for o in result["observations"]}
    for checkpoint in ("result", "persisted"):
        observation = found[("F01", "api", checkpoint)]
        fact = next(f for f in observation["data"]["facts"] if f["key"] == "group_size")
        assert (fact["value"], fact["status"]) == ("999", "customer_confirmed")
        assert fact["source_message_id"] == observation["data"]["current_message_id"]
        assert (
            "Your booking is confirmed."
            in found[("G01", "api", checkpoint)]["data"]["reply"]["body_text"]
        )
    for case_id in ("F01", "G01"):
        saved = found[(case_id, "api", "persisted")]["data"]
        assert saved["query_executed"] and saved["record_exists"]
        assert all(saved["api_comparison"].values())
    for case_id, error in (
        ("G03", "unsupported_answer_evidence"),
        ("G06", "unsupported_numeric_claim"),
    ):
        assert found[(case_id, "main", "result")]["data"]["rejection_code"] == error
    assert len(result["expected_keys"]) == len({tuple(k) for k in result["expected_keys"]})


def test_f05_complete_chain_preserves_human_confirmation_protection():
    case = cases("F05")[0]
    for prior_status, expected_status, expected_value in (
        ("customer_confirmed", "customer_confirmed", "9"),
        ("human_confirmed", "conflicted", "8 / 9"),
    ):
        payload = deepcopy(case["payload"])
        payload["previous_facts"][0]["status"] = prior_status
        recorded = RecordedClient(QueueClient([payload["mock_response"]]), RequestBudget(1), "mock")
        result, status, _ = understanding_data(
            payload, QwenConversationLLM(recorded, "test"), recorded
        )
        fact = result["facts"][0]
        assert status == "completed"
        assert (fact["value"], fact["status"], fact["source_message_id"]) == (
            expected_value,
            expected_status,
            "m2",
        )
        recorded.close()


def test_live_three_trials_use_fresh_clients_and_record_actual_stage_requests():
    created = []
    result = run_quality_suite(
        "live", project_root=ROOT, live_client_factory=successful_live_factory(created)
    )
    assert len(created) == 30
    assert len({id(item[-1]) for item in created}) == 30
    assert all(item[-1].closed for item in created)
    assert {o["trial_id"] for o in result["observations"]} == {"1", "2", "3"}
    assert all(o["execution_status"] == "completed" for o in result["observations"])
    assert result["metadata"]["model_request_count"] == 48
    assert result["metadata"]["real_model_calls"] == 0
    assert result["metadata"]["live_simulated"] is True
    assert result["metadata"]["response_cache_enabled"] is False
    assert all(
        call["usage"] == "unknown"
        for call in result["metadata"]["model_calls"]
        if call["call_count"]
    )
    assert all(
        call["system_prompt_sha256"]
        for call in result["metadata"]["model_calls"]
        if call["call_count"]
    )


def test_live_timeout_fallback_is_observed_as_model_error_with_business_result():
    def factory(case, trial, probe):
        return QueueClient([APITimeoutError(request=Mock())])

    result = run_quality_suite(
        "live", cases=cases("western_sichuan_product"), live_client_factory=factory
    )
    assert result["metadata"]["model_request_count"] == 3
    for observed in result["observations"]:
        assert observed["data"]["reply"]["generation_method"] == "rag_grounded_template"
        assert observed["stages"][0]["provider_execution"] == "error"
        assert observed["stages"][0]["fallback_used"] is True
        assert observed["stages"][1]["provider_execution"] == "not_called"
        assert observed["stages"][1]["expected_to_run"] is True
        assert observed["stages"][1]["upstream_blocked"] is True


def test_request_budget_never_sends_an_over_limit_request_and_keeps_unrun_rows():
    created = []
    result = run_quality_suite(
        "live",
        cases=cases("western_sichuan_product", "F03"),
        max_requests=2,
        live_client_factory=successful_live_factory(created),
    )
    assert result["metadata"]["model_request_count"] == 2
    assert result["metadata"]["budget_exhausted"] is True
    assert sum(call["call_count"] for call in result["metadata"]["model_calls"]) == 2
    assert any(o["execution_status"] == "not_run" for o in result["observations"])
    assert len(result["observations"]) == 6


@pytest.mark.parametrize(
    "options",
    [
        {"mode": "unknown"},
        {"mode": "live"},
        {"mode": "live", "allow_network": True},
        {"mode": "live", "allow_network": True, "live_config": {"api_key": "unused", "timeout": 0}},
        {"mode": "live", "allow_network": True, "live_config": {"api_key": "unused", "model": " "}},
        {"mode": "rule_only", "trials": 3},
        {"mode": "mocked_model", "max_requests": 0},
    ],
)
def test_invalid_or_missing_configuration_does_not_silently_change_mode(options):
    with pytest.raises(QualityConfigurationError):
        run_quality_suite(**options)


def test_process_environment_cannot_select_database_or_live_services(monkeypatch, tmp_path):
    sentinel = tmp_path / "must-not-open.sqlite3"
    monkeypatch.setenv("CONVERSATION_DATABASE_URL", "sqlite:///" + sentinel.as_posix())
    monkeypatch.setenv("CONVERSATION_LLM_ENABLED", "true")
    monkeypatch.setenv("NOTION_CRM_ENABLED", "true")
    monkeypatch.setenv("SERVICE_ACCESS_MODE", "protected")
    monkeypatch.setenv("SERVICE_ACCESS_TOKEN", "invalid-short-token")
    settings = isolated_settings(ROOT, tmp_path / "isolated.sqlite3")
    assert settings.conversation_database_url is None
    assert settings.conversation_llm_enabled is False
    assert settings.notion_crm_enabled is False
    result = run_quality_suite("rule_only", cases=cases("M06"), work_root=tmp_path)
    assert result["observations"][0]["execution_status"] == "completed"
    assert not sentinel.exists()
    assert not list(tmp_path.glob("case-*"))


def _projection(result):
    rows = evaluate_assertions(
        result["cases"], result["observations"], mode=result["metadata"]["mode"], trials=1
    )
    return sorted(
        (
            r["case_id"],
            r["probe_id"],
            r["checkpoint"],
            r["assertion_id"],
            r["execution_status"],
            r.get("behavior_status"),
            r.get("failure_type"),
        )
        for r in rows
    )


def test_individual_batch_reverse_order_preserve_grades(offline_runs):
    ordered = [c for c in load_cases(ROOT) if "mocked_model" in c["applicable_modes"]]
    reverse = run_quality_suite("mocked_model", cases=list(reversed(ordered)))
    assert _projection(reverse) == _projection(offline_runs["mocked_model"])
    first = run_quality_suite("mocked_model", cases=cases("F01"))
    assert _projection(first) == [
        row for row in _projection(offline_runs["mocked_model"]) if row[0] == "F01"
    ]


def test_duplicate_keys_and_unregistered_adapters_rejected_before_execution():
    case = cases("F03")[0]
    with pytest.raises(QualityConfigurationError, match="duplicate case"):
        run_quality_suite("mocked_model", cases=[case, case])
    case["assertions"].append(deepcopy(case["assertions"][0]))
    with pytest.raises(QualityConfigurationError, match="duplicate assertion"):
        run_quality_suite("mocked_model", cases=[case])
    case["adapter"] = "arbitrary.import.path"
    with pytest.raises(QualityConfigurationError, match="unregistered"):
        run_quality_suite("mocked_model", cases=[case])


def test_unexpected_adapter_failure_is_execution_error(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("synthetic adapter failure")

    monkeypatch.setattr("lead_cleaner.evaluation.quality_runner.memory_data", broken)
    result = run_quality_suite("rule_only", cases=cases("M01"))
    assert result["observations"][0]["execution_status"] == "error"
    assert result["observations"][0]["error_type"] == "RuntimeError"


def test_fact_validator_rejection_and_provider_error_are_different():
    case = cases("F03")[0]
    case["payload"]["mock_response"]["updates"][0]["evidence"] = "not present"
    result = run_quality_suite("mocked_model", cases=[case])
    observed = result["observations"][0]
    assert observed["execution_status"] == "completed"
    assert observed["data"]["rejection_code"] == "unsupported_fact_evidence"
    assert observed["stages"][0]["validation_result"] == "rejected"
    assert observed["stages"][0]["provider_execution"] == "succeeded"
