"""Failure and isolation checks for the standalone evaluation transport."""

import json
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from openai import APITimeoutError

from lead_cleaner.evaluation._quality_adapters import (
    _finish_api_stages,
    finish_boundary,
    generation_data,
    run_api,
)
from lead_cleaner.evaluation._quality_runtime import (
    NetworkGuard,
    QualityConfigurationError,
    QueueClient,
    RecordedClient,
    RequestBudget,
)
from lead_cleaner.evaluation.quality_runner import load_cases, run_quality_suite
from lead_cleaner.services.conversation_llm import QwenConversationLLM

ROOT = Path(__file__).resolve().parents[1]


def case(case_id):
    return next(value for value in load_cases(ROOT) if value["case_id"] == case_id)


@pytest.mark.parametrize(
    "target", ["http://example.com", "https://user:password@example.com", "https:///missing"]
)
def test_network_guard_rejects_unsafe_target_configuration(target):
    with pytest.raises(QualityConfigurationError):
        NetworkGuard(target)


def test_guard_blocks_connect_connect_ex_and_dns_without_contacting_network():
    with NetworkGuard() as guard:
        for method in ("connect", "connect_ex"):
            with socket.socket() as sock, pytest.raises(OSError, match="blocked"):
                getattr(sock, method)(("203.0.113.7", 443))
        with pytest.raises(OSError, match="DNS"):
            socket.getaddrinfo("not-permitted.invalid", 443)
        assert NetworkGuard._local("localhost") is True
        assert NetworkGuard._local("::1") is True
        assert NetworkGuard._local("not-local.invalid") is False
        guard._check("local-unix-socket")
    assert guard.summary()["external_blocked"] == 3


def test_live_target_dns_and_ip_allowlist_and_loopback(monkeypatch):
    calls = []
    monkeypatch.setattr(socket.socket, "connect", lambda self, address: calls.append(address))
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, address: 0)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.8", port))
        ],
    )
    with NetworkGuard("https://model.example:8443/v1") as guard:
        socket.getaddrinfo(b"model.example", 8443)
        with socket.socket() as sock:
            sock.connect(("203.0.113.8", 8443))
            sock.connect(("model.example", 8443))
            assert sock.connect_ex(("127.0.0.1", 4444)) == 0
            with pytest.raises(OSError):
                sock.connect(("203.0.113.8", 443))
        socket.getaddrinfo("localhost", 4444)
    assert len(calls) == 2
    assert guard.summary()["target_connections"] == 2
    assert guard.summary()["loopback_connections"] == 1


def test_guard_works_in_plain_python_without_pytest_socket_plugin():
    script = """
import socket
from lead_cleaner.evaluation._quality_runtime import NetworkGuard
with NetworkGuard() as guard:
    try:
        with socket.socket() as sock:
            sock.connect(('203.0.113.10',443))
    except OSError:
        print(guard.blocked_attempts)
    else:
        raise AssertionError('network guard bypassed')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"


def test_recorded_client_captures_returned_usage_and_closes_delegate():
    delegate = Mock()
    delegate.chat.completions.create.return_value = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12)
    )
    recorded = RecordedClient(delegate, RequestBudget(1), "mock")
    request = dict(
        model="synthetic",
        messages=[{"content": "system"}, {"content": json.dumps({"current_message": "hello"})}],
        max_tokens=1800,
        temperature=0,
    )
    recorded.create(**request)
    assert recorded.records[0]["output_schema_sha256"] == "unknown"
    assert recorded.records[0]["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
    }
    recorded.close()
    delegate.close.assert_called_once()
    other = RecordedClient(Mock(), RequestBudget(1), "mock")
    finish_boundary(other, None)


def test_usage_pydantic_dump_and_strict_mock_queue():
    delegate = Mock()
    usage = Mock()
    usage.model_dump.return_value = {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    delegate.chat.completions.create.return_value = SimpleNamespace(usage=usage)
    recorded = RecordedClient(delegate, RequestBudget(1), "mock")
    recorded.create(messages=[{"content": "s"}, {"content": "{}"}])
    assert recorded.records[0]["usage"]["total_tokens"] == 7
    with pytest.raises(RuntimeError, match="queue_exhausted"):
        QueueClient([]).create()


def test_generation_timeout_is_execution_error_not_successful_claim_block():
    payload = case("G04")["payload"]
    recorded = RecordedClient(
        QueueClient([APITimeoutError(request=Mock())]), RequestBudget(1), "mock"
    )
    data, execution, code = generation_data(
        payload, QwenConversationLLM(recorded, "test"), recorded
    )
    assert execution == "error" and code == "timeout"
    assert data["reply"] is None
    assert recorded.records[0]["validation_result"] == "not_reached"


def test_api_validation_rejection_is_separate_from_provider_success():
    recorded = RecordedClient(QueueClient([]), RequestBudget(1), "mock")
    recorded.records.append(
        {"turn": 1, "stage": "generation", "provider_execution": "succeeded", "error_type": None}
    )
    _finish_api_stages(
        recorded,
        {"understanding": "succeeded", "generation": "fallback:unsupported_answer_evidence"},
        1,
        ["understanding", "generation"],
    )
    row = recorded.records[0]
    assert row["validation_result"] == "rejected"
    assert row["error_type"] == "unsupported_answer_evidence"
    assert row["fallback_used"] is True


def test_live_sdk_construction_uses_only_target_and_disables_environment_proxy(monkeypatch):
    captured = []
    payload = case("F03")["payload"]

    def sdk(**kwargs):
        captured.append(kwargs)
        kwargs["http_client"].close()
        return QueueClient([payload["mock_response"]])

    monkeypatch.setattr("lead_cleaner.evaluation.quality_runner.OpenAI", sdk)
    result = run_quality_suite(
        "live",
        cases=[case("F03")],
        allow_network=True,
        live_config={
            "api_key": "synthetic-unused",
            "model": "synthetic-model",
            "base_url": "https://model.example/v1",
            "timeout": 3,
        },
    )
    assert len(captured) == 3
    assert all(item["max_retries"] == 0 and item["timeout"] == 3 for item in captured)
    assert all(o["execution_status"] == "completed" for o in result["observations"])
    assert result["metadata"]["socket_guard"]["target_connections"] == 0
    assert result["metadata"]["model_endpoint"] == "https://model.example/v1"
    assert result["metadata"]["model_timeout_seconds"] == 3
    assert result["metadata"]["runner_version"] == "p0-quality-runner.v1"
    assert "synthetic-unused" not in json.dumps(result["metadata"])
    assert all(
        record["output_schema_sha256"] != "unknown" for record in result["metadata"]["model_calls"]
    )


def test_http_error_is_recorded_and_does_not_pass_safety_assertions(tmp_path):
    sample = case("M06")
    sample["payload"]["turns"] = [""]
    data, saved, status, error = run_api(
        ROOT, tmp_path / "invalid.sqlite3", sample, "main", None, None
    )
    assert status == "error" and error == "http_422"
    assert saved is None
    assert data["turns"] == [{"turn": 1, "http_status": 422}]


@pytest.mark.parametrize("failure", ["duplicate", "adapter"])
def test_case_loader_rejects_duplicate_ids_and_arbitrary_entrypoints(tmp_path, failure):
    folder = tmp_path / "data/evals"
    folder.mkdir(parents=True)
    (folder / "multi_turn_conversations.jsonl").write_text("", encoding="utf-8")
    sample = case("F03")
    if failure == "adapter":
        sample["adapter"] = "arbitrary_entrypoint"
    contents = json.dumps(sample) + "\n"
    (folder / "p0_quality_cases.v1.jsonl").write_text(
        contents * (2 if failure == "duplicate" else 1), encoding="utf-8"
    )
    with pytest.raises(QualityConfigurationError):
        load_cases(tmp_path)


def test_model_adapter_cannot_run_in_rule_mode():
    sample = case("F03")
    sample["applicable_modes"] = ["rule_only"]
    result = run_quality_suite("rule_only", cases=[sample])
    assert result["observations"][0]["execution_status"] == "error"
    assert result["observations"][0]["error_type"] == "QualityConfigurationError"


def test_interruption_keeps_prior_probe_and_interrupted_sdk_evidence(tmp_path):
    journal = tmp_path / "diagnostics/events.jsonl"
    sample = case("F03")
    clients = []

    def factory(current_case, trial, probe):
        def interrupted(**kwargs):
            raise KeyboardInterrupt()

        response = sample["payload"]["mock_response"] if trial == "1" else interrupted
        client = QueueClient([response])
        clients.append(client)
        return client

    with pytest.raises(KeyboardInterrupt):
        run_quality_suite("live", cases=[sample], live_client_factory=factory, journal_path=journal)
    events = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert [item["event"] for item in events] == ["model_call", "observation", "model_call"]
    assert events[1]["observation"]["execution_status"] == "completed"
    assert events[2]["trial_id"] == "2"
    assert events[2]["record"]["error_type"] == "KeyboardInterrupt"
    assert events[2]["record"]["provider_execution"] == "error"
    assert events[0]["record"]["response_choices"][0]["content"]
    assert events[0]["record"]["response_sha256"]
    assert all(client.closed for client in clients)
    assert not (journal.parent / "COMPLETED").exists()


def test_journal_records_errors_and_budget_unrun_without_credentials(tmp_path, monkeypatch):
    sample = case("F03")
    journal = tmp_path / "events.jsonl"
    result = run_quality_suite(
        "live",
        cases=[sample],
        max_requests=1,
        live_config={"api_key": "must-never-appear"},
        live_client_factory=lambda *args: QueueClient([sample["payload"]["mock_response"]]),
        journal_path=journal,
    )
    text = journal.read_text(encoding="utf-8")
    assert "must-never-appear" not in text
    events = [json.loads(line) for line in text.splitlines()]
    observed = [item["observation"] for item in events if item["event"] == "observation"]
    assert observed == result["observations"]
    assert observed[-1]["execution_status"] == "not_run"

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic")

    monkeypatch.setattr("lead_cleaner.evaluation.quality_runner.memory_data", broken)
    error_journal = tmp_path / "errors.jsonl"
    run_quality_suite("rule_only", cases=[case("M01")], journal_path=error_journal)
    assert (
        json.loads(error_journal.read_text(encoding="utf-8"))["observation"]["execution_status"]
        == "error"
    )


def test_legacy_loader_preserves_future_explicit_review_without_fabricating_it(tmp_path):
    folder = tmp_path / "data/evals"
    folder.mkdir(parents=True)
    legacy = json.loads(
        (ROOT / "data/evals/multi_turn_conversations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    legacy.update(
        review_status="reviewed",
        reviewer="synthetic-test-reviewer",
        reviewed_at="2026-10-04",
        review_reason="synthetic loader test",
    )
    (folder / "multi_turn_conversations.jsonl").write_text(json.dumps(legacy), encoding="utf-8")
    (folder / "p0_quality_cases.v1.jsonl").write_text("", encoding="utf-8")
    loaded = load_cases(tmp_path)[0]
    assert loaded["review_status"] == "reviewed"
    assert loaded["reviewer"] == "synthetic-test-reviewer"
    assert loaded["reviewed_at"] == "2026-10-04"
    assert loaded["review_reason"] == "synthetic loader test"
    assert all(item["review_status"] == "draft" for item in load_cases(ROOT))


def test_output_schema_hash_is_separate_and_unknown_when_prompt_has_no_valid_schema():
    from lead_cleaner.evaluation._quality_runtime import digest

    for system, expected in [
        ("synthetic", "unknown"),
        ("Schema: not-json", "unknown"),
        ('Schema: {"type":"object"}', digest({"type": "object"})),
    ]:
        recorded = RecordedClient(QueueClient([{"updates": []}]), RequestBudget(1), "mock")
        recorded.create(messages=[{"content": system}, {"content": "{}"}])
        assert recorded.records[0]["output_schema_sha256"] == expected
        assert recorded.records[0]["system_prompt_sha256"]
        recorded.close()


def test_rule_mode_describes_effective_isolation_without_random_paths_or_credentials():
    result = run_quality_suite("rule_only", cases=[case("M01")])
    meta = result["metadata"]
    assert meta["prompt_observation_status"] == "not_applicable"
    assert meta["output_schema_observation_status"] == "not_applicable"
    assert meta["model_endpoint"] is None and meta["model_timeout_seconds"] is None
    assert meta["effective_settings"]["app_mode"] == "rule_only"
    assert meta["effective_settings"]["allow_network"] is False
    assert meta["effective_settings"]["conversation_llm_enabled"] is False
    assert meta["effective_settings"]["notion_crm_enabled"] is False
    assert not any(
        "key" in field or "path" in field or "token" in field
        for field in meta["effective_settings"]
    )
