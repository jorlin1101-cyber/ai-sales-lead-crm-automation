"""Execution tests exercise real production API/retrieval without paid providers."""

from __future__ import annotations

import copy
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError

from lead_cleaner.answerability_evaluation import adapters, retrieval
from lead_cleaner.answerability_evaluation.dataset import load_dataset
from lead_cleaner.rag.retriever import RagRetrievalOutcome

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def dataset():
    return load_dataset(ROOT)


def select(dataset, *ids):
    result = copy.deepcopy(dataset)
    result["cases"] = [case for case in result["cases"] if case["case_id"] in ids]
    return result


@pytest.mark.parametrize("mode", adapters.MODES)
def test_actual_api_isolates_cases_and_preserves_each_turn(dataset, tmp_path, monkeypatch, mode):
    data = select(dataset, "AB03", "AB19", "AB20")
    settings_seen = []
    original = adapters.create_app

    def create_app(*, settings):
        settings_seen.append(settings)
        assert settings.allow_network is False
        assert settings.dashscope_api_key is None
        assert settings.conversation_database_url is None
        assert settings.conversation_llm_enabled is False
        assert not settings.notion_crm_enabled
        return original(settings=settings)

    monkeypatch.setattr(adapters, "create_app", create_app)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "NEVER_LOAD_ENV_SENTINEL")
    monkeypatch.setenv("CONVERSATION_DATABASE_URL", "invalid-environment-database")
    (tmp_path / ".env").write_text("ALLOW_NETWORK=true\nDASHSCOPE_API_KEY=NEVER_LOAD_FILE_SENTINEL")
    rows = adapters.run_observations(tmp_path, data, mode, tmp_path / "runs")
    assert len(rows) == 7
    assert all(r["execution_status"] == "completed" and r["api_status"] == 200 for r in rows)
    assert len({str(s.conversation_db_path) for s in settings_seen}) == 3
    assert all(not Path(s.conversation_db_path).exists() for s in settings_seen)
    assert all(r["predicted_answerability"] is None for r in rows)
    assert all(r["network_guard"]["external_blocked"] == 0 for r in rows)
    assert all(r["protocol_id"] == "p0-02.v1" and r["trial_id"] == "1" for r in rows)
    assert "SENTINEL" not in json.dumps(rows)
    for case in data["cases"]:
        observed = [r for r in rows if r["case_id"] == case["case_id"]]
        assert [r["turn_id"] for r in observed] == [t["turn_id"] for t in case["turns"]]
        assert observed[0]["history"] == []
        assert [r["response"]["turn_number"] for r in observed] == list(range(1, len(observed) + 1))
        for number, row in enumerate(observed):
            assert set(row["message_id_map"]) == {t["turn_id"] for t in case["turns"][: number + 1]}
            assert row["facts"] == row["response"]["confirmed_facts"]
            assert row["state"] == row["response"]["state"]
            for fact in row["facts"]:
                assert fact["source_message_id"] in row["message_id_map"].values()
    first = rows[0]
    assert first["retrieval_calls"] and first["provided_context_rule"]
    if mode == "rule_only":
        assert not first["model_calls"]
        assert all(
            not s["applicable"] and s["provider_execution"] == "not_called" for s in first["stages"]
        )
        assert first["provided_context"] == first["provided_context_rule"]
    else:
        assert len(first["model_calls"]) == 2
        assert first["stages"][1]["validation_result"] == "accepted"
        assert first["provided_context"] == first["provided_context_model"]
        generation = json.loads(first["model_calls"][1]["request"]["messages"][-1]["content"])
        assert {e["chunk_id"] for e in generation["evidence"]} == {
            c["chunk_id"] for c in first["provided_context_model"]
        }


def test_gold_and_future_messages_never_enter_system_inputs(dataset, tmp_path):
    data = select(dataset, "AB20")
    turns = data["cases"][0]["turns"]
    turns[2]["message"] += " FUTURE_CUSTOMER_MESSAGE_SENTINEL"
    for turn in turns:
        for name in ("answerability", "facets", "expected_facts", "customer_facts", "judgments"):
            turn[name] = "HIDDEN_GOLD_SENTINEL"
    for snapshot in data["snapshots"].values():
        for chunk in snapshot["chunks"]:
            chunk["validity_basis"] = "HIDDEN_GOLD_SENTINEL"
    rows = adapters.run_observations(ROOT, data, "mocked_model", tmp_path)
    assert all(r["api_status"] == 200 for r in rows)
    assert "HIDDEN_GOLD_SENTINEL" not in json.dumps(rows)
    assert "FUTURE_CUSTOMER_MESSAGE_SENTINEL" not in json.dumps(rows[:2])
    assert turns[0]["message"] in rows[1]["history"]
    assert turns[1]["message"] in rows[2]["history"]


@pytest.mark.parametrize("stage", ["understanding", "generation"])
@pytest.mark.parametrize("failure", ["timeout", "invalid"])
def test_model_error_keeps_safe_fallback_separate(dataset, tmp_path, monkeypatch, stage, failure):
    original = adapters.ControlledClient.respond

    def respond(payload):
        actual_stage = "generation" if "evidence" in payload else "understanding"
        if actual_stage == stage:
            if failure == "timeout":
                raise APITimeoutError(request=httpx.Request("POST", "https://never-called.example"))
            return {"invalid_schema": True}
        return original(payload)

    monkeypatch.setattr(adapters.ControlledClient, "respond", staticmethod(respond))
    row = adapters.run_observations(ROOT, select(dataset, "AB03"), "mocked_model", tmp_path)[0]
    assert row["api_status"] == 200 and row["reply_text"] and row["state"]
    assert row["execution_status"] == "error"
    assert row["error_type"] == ("timeout" if failure == "timeout" else "invalid_structured_output")
    observed = next(s for s in row["stages"] if s["stage"] == stage)
    assert observed["fallback_used"] is True and observed["call_count"] == 1
    assert observed["provider_execution"] == ("error" if failure == "timeout" else "succeeded")
    assert observed["validation_result"] == ("not_reached" if failure == "timeout" else "rejected")
    assert row["provided_context"] == row["provided_context_rule"]


@pytest.mark.parametrize("operation", ["dns", "connect", "connect_ex"])
def test_external_network_is_blocked_before_transport(dataset, tmp_path, monkeypatch, operation):
    def respond(payload):
        if operation == "dns":
            socket.getaddrinfo("never-contact.example", 443)
        else:
            with socket.socket() as connection:
                getattr(connection, operation)(("203.0.113.19", 443))
        raise AssertionError("transport must be blocked")

    monkeypatch.setattr(adapters.ControlledClient, "respond", staticmethod(respond))
    row = adapters.run_observations(ROOT, select(dataset, "AB03"), "mocked_model", tmp_path)[0]
    assert row["execution_status"] == "error"
    assert row["network_guard"]["external_blocked"] == 1
    assert row["stages"][0]["error_type"] == "unexpected_client_error"


def test_retrieval_exception_is_not_a_safe_success(dataset, tmp_path, monkeypatch):
    from lead_cleaner.rag.retriever import HybridRagRetriever

    def fail(*args, **kwargs):
        raise RuntimeError("retrieval unavailable")

    monkeypatch.setattr(HybridRagRetriever, "retrieve", fail)
    row = adapters.run_observations(ROOT, select(dataset, "AB03"), "rule_only", tmp_path)[0]
    assert row["api_status"] == 200 and row["reply_text"]
    assert row["execution_status"] == "error" and row["error_type"] == "RuntimeError"
    assert row["retrieval_calls"][0]["error_type"] == "RuntimeError"


def test_explicit_unavailable_retriever_and_product_lookup_are_recorded():
    current = {"retrieval_calls": [], "retrieved_chunks": []}
    delegate = SimpleNamespace(
        retrieve=lambda query: RagRetrievalOutcome(
            retrieval_method="unavailable", failure_reason="retrieval_failure"
        ),
        product_manuals=lambda region: [],
    )
    recorder = adapters.RecordingRetriever(delegate, {"current": current})
    recorder.retrieve("query")
    recorder.product_manuals("general")
    assert current["retrieval_calls"][0]["error_type"] == "retrieval_failure"
    assert current["retrieval_calls"][1]["method"] == "product_manuals"


@pytest.mark.parametrize("failure", ["http", "json", "exception", "interrupt", "startup"])
def test_failed_turn_retains_remaining_planned_observations(
    dataset, tmp_path, monkeypatch, failure
):
    data = select(dataset, "AB19", "AB20")
    original = adapters.TestClient.post
    calls = []

    def post(self, *args, **kwargs):
        calls.append(kwargs["json"]["external_message_id"])
        if len(calls) == 2:
            if failure == "http":
                return httpx.Response(503, json={"detail": "unavailable"})
            if failure == "json":
                return httpx.Response(500, text="not-json")
            if failure == "exception":
                raise RuntimeError("simulated local API failure")
            if failure == "interrupt":
                raise KeyboardInterrupt
        return original(self, *args, **kwargs)

    def bad_start(**kwargs):
        raise OSError("database unavailable")

    monkeypatch.setattr(adapters.TestClient, "post", post)
    if failure == "startup":
        monkeypatch.setattr(adapters, "create_app", bad_start)
    rows = adapters.run_observations(ROOT, data, "rule_only", tmp_path)
    assert len(rows) == 6
    if failure == "startup":
        assert [r["execution_status"] for r in rows] == ["error", "not_run", "not_run"] * 2
    else:
        assert [r["execution_status"] for r in rows[:3]] == ["completed", "error", "not_run"]
        assert rows[0]["response"]["turn_number"] == 1
        assert all(
            r["execution_status"] == ("not_run" if failure == "interrupt" else "completed")
            for r in rows[3:]
        )
        assert rows[2]["error_type"] == (
            "interrupted" if failure == "interrupt" else "previous_turn_failed"
        )


def test_invalid_mode_and_duplicate_turns_rejected_before_execution(dataset, tmp_path):
    with pytest.raises(ValueError, match="only rule_only"):
        adapters.run_observations(ROOT, dataset, "live", tmp_path)
    data = select(dataset, "AB03")
    data["cases"].append(copy.deepcopy(data["cases"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        adapters.run_observations(ROOT, data, "rule_only", tmp_path)


def test_all_three_paths_use_actual_retrieval_queries_and_top_k(dataset, monkeypatch):
    calls = []
    original = retrieval.retrieve_hybrid

    def observe(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(retrieval, "retrieve_hybrid", observe)
    rows = retrieval.run_retrieval(dataset)
    assert len(rows) == 54
    assert all(r["execution_status"] == "completed" for r in rows)
    assert {(r["case_id"], r["path"]) for r in rows} == {
        (f"AB{number:02d}", path) for number in range(1, 19) for path in retrieval.PATHS
    }
    assert len(calls) == sum(len(r["retrieval_queries"]) for r in rows)
    assert all(c["top_k"] == 3 and c["candidate_top_k"] == 5 and c["rrf_k"] == 60 for c in calls)
    assert all(len(r["results"]) <= 3 for r in rows)
    assert all(c["retrieval_source"] == "fusion" for r in rows for c in r["results"])
    assert rows[0]["retrieval_queries"] == [rows[0]["query"]]
    assert rows[1]["retrieval_queries"] != rows[0]["retrieval_queries"]
    assert len(rows[2]["retrieval_queries"]) == 2
    assert all(r["network_guard"]["external_blocked"] == 0 for r in rows)


def test_retrieval_is_sensitive_to_actual_text_not_judgments(dataset):
    data = select(dataset, "AB03")
    baseline = retrieval.run_retrieval(data)
    turn = data["cases"][0]["turns"][0]
    turn["judgments"] = {"made-up-gold": 3}
    turn["facets"] = "HIDDEN_GOLD_SENTINEL"
    relabeled = retrieval.run_retrieval(data)
    assert [r["results"] for r in relabeled] == [r["results"] for r in baseline]
    snapshot = data["snapshots"][data["cases"][0]["snapshot_id"]]
    for item in snapshot["chunks"]:
        item["chunk"]["text"] = "Astronomical telescope calibration unrelated material."
    changed = retrieval.run_retrieval(data)
    assert changed[0]["results"] != baseline[0]["results"]


@pytest.mark.parametrize("failure", ["error", "interrupt"])
def test_retrieval_failure_keeps_all_planned_paths(dataset, monkeypatch, failure):
    def fail(**kwargs):
        if failure == "interrupt":
            raise KeyboardInterrupt
        raise RuntimeError("injected retrieval failure")

    monkeypatch.setattr(retrieval, "retrieve_hybrid", fail)
    rows = retrieval.run_retrieval(select(dataset, "AB03", "AB04"))
    assert len(rows) == 6
    assert rows[0]["execution_status"] == "error"
    assert all(
        r["execution_status"] == ("not_run" if failure == "interrupt" else "error")
        for r in rows[1:]
    )


def test_fused_single_query_uses_real_result_without_artificial_fusion(dataset, monkeypatch):
    monkeypatch.setattr(retrieval, "build_retrieval_queries", lambda lead, features: [lead.message])
    rows = retrieval.run_retrieval(select(dataset, "AB03"))
    assert rows[0]["results"] == rows[2]["results"]
