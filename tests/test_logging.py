import json
import logging

from fastapi.testclient import TestClient

from lead_cleaner.api import main as api_main
from lead_cleaner.api.main import create_app
from lead_cleaner.config import AppMode, RagBackend, Settings
from lead_cleaner.observability import LOGGER_NAME, build_log_payload


PRIVATE_EMAIL = "private.person@example.com"
PRIVATE_MESSAGE = "Private itinerary details must not enter application logs."


def make_app():
    return create_app(
        settings=Settings(
            _env_file=None,
            app_mode=AppMode.RULE_ONLY,
            allow_network=False,
            rag_backend=RagBackend.DISABLED,
        )
    )


def _lead_cleaner_payloads(caplog) -> list[dict[str, object]]:
    return [
        json.loads(record.getMessage()) for record in caplog.records if record.name == LOGGER_NAME
    ]


def test_success_logs_are_structured_correlated_and_do_not_contain_lead_pii(caplog) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    with TestClient(make_app()) as client:
        response = client.post(
            "/process-lead",
            json={"email": PRIVATE_EMAIL, "message": PRIVATE_MESSAGE},
            headers={"X-Request-ID": "logging-test-001"},
        )

    assert response.status_code == 200
    payloads = _lead_cleaner_payloads(caplog)
    events = {payload["event"] for payload in payloads}
    assert {
        "request_started",
        "lead_processing_completed",
        "request_completed",
    }.issubset(events)
    correlated = [
        payload
        for payload in payloads
        if payload.get("event") in events and "request_id" in payload
    ]
    assert correlated
    assert all(payload["request_id"] == "logging-test-001" for payload in correlated)
    assert PRIVATE_EMAIL not in caplog.text
    assert PRIVATE_MESSAGE not in caplog.text


def test_unexpected_error_log_records_only_safe_error_type(caplog, monkeypatch) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    private_error = "provider response contained Bearer private-token-value"

    def raise_unexpected_error(*args, **kwargs):
        raise RuntimeError(private_error)

    monkeypatch.setattr(api_main, "process_lead", raise_unexpected_error)
    with TestClient(make_app(), raise_server_exceptions=False) as client:
        response = client.post(
            "/process-lead",
            json={"email": PRIVATE_EMAIL, "message": PRIVATE_MESSAGE},
            headers={"X-Request-ID": "logging-failure-001"},
        )

    assert response.status_code == 500
    payloads = _lead_cleaner_payloads(caplog)
    assert any(
        payload.get("event") == "transport_error"
        and payload.get("error_code") == "internal_error"
        and payload.get("error_type") == "RuntimeError"
        for payload in payloads
    )
    assert private_error not in caplog.text
    assert PRIVATE_EMAIL not in caplog.text
    assert PRIVATE_MESSAGE not in caplog.text


def test_log_payload_redacts_unknown_fields_and_secret_shaped_safe_values() -> None:
    payload = build_log_payload(
        "request_completed",
        request_id="safe-request-id",
        email=PRIVATE_EMAIL,
        path="/process-lead?token=private-secret-value",
    )

    assert payload["request_id"] == "safe-request-id"
    assert payload["email"] == "[REDACTED]"
    assert payload["path"] == "[REDACTED]"
