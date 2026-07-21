import re

from fastapi.testclient import TestClient

from lead_cleaner.api import main as api_main
from lead_cleaner.api.main import create_app
from lead_cleaner.api.request_context import REQUEST_ID_HEADER
from lead_cleaner.config import AppMode, RagBackend, Settings


UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
VALID_PAYLOAD = {
    "email": "safe@example.com",
    "message": "Please prepare a private Yunnan tour proposal.",
}


def make_app():
    return create_app(
        settings=Settings(
            _env_file=None,
            app_mode=AppMode.RULE_ONLY,
            allow_network=False,
            rag_backend=RagBackend.DISABLED,
        )
    )


def test_server_generates_a_unique_request_id_for_each_request() -> None:
    with TestClient(make_app()) as client:
        first = client.get("/health")
        second = client.get("/health")

    first_id = first.headers[REQUEST_ID_HEADER]
    second_id = second.headers[REQUEST_ID_HEADER]
    assert UUID_PATTERN.fullmatch(first_id)
    assert UUID_PATTERN.fullmatch(second_id)
    assert first_id != second_id


def test_safe_caller_request_id_is_preserved() -> None:
    with TestClient(make_app()) as client:
        response = client.get(
            "/health",
            headers={REQUEST_ID_HEADER: "n8n-run_20260721.001"},
        )

    assert response.headers[REQUEST_ID_HEADER] == "n8n-run_20260721.001"


def test_unsafe_caller_request_id_is_replaced() -> None:
    with TestClient(make_app()) as client:
        response = client.get(
            "/health",
            headers={REQUEST_ID_HEADER: "unsafe value with spaces and customer@example.com"},
        )

    assert UUID_PATTERN.fullmatch(response.headers[REQUEST_ID_HEADER])


def test_request_validation_error_is_structured_and_does_not_echo_input() -> None:
    private_text = "private customer message must never be echoed"
    with TestClient(make_app()) as client:
        response = client.post(
            "/process-lead",
            json={
                "message": private_text,
                "unexpected_private_field": "secret-value",
            },
            headers={REQUEST_ID_HEADER: "validation-test-001"},
        )

    assert response.status_code == 422
    assert response.headers[REQUEST_ID_HEADER] == "validation-test-001"
    detail = response.json()["detail"]
    assert detail["code"] == "request_validation_error"
    assert detail["request_id"] == "validation-test-001"
    assert isinstance(detail["errors"], list)
    assert private_text not in response.text
    assert "secret-value" not in response.text
    assert all("input" not in error for error in detail["errors"])


def test_unexpected_error_returns_safe_500_with_request_id(monkeypatch) -> None:
    private_error = "provider leaked sk-not-a-real-secret-value"

    def raise_unexpected_error(*args, **kwargs):
        raise RuntimeError(private_error)

    monkeypatch.setattr(api_main, "process_lead", raise_unexpected_error)
    with TestClient(make_app(), raise_server_exceptions=False) as client:
        response = client.post(
            "/process-lead",
            json=VALID_PAYLOAD,
            headers={REQUEST_ID_HEADER: "failure-test-001"},
        )

    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER] == "failure-test-001"
    assert response.json()["detail"] == {
        "code": "internal_error",
        "message": "The service failed unexpectedly.",
        "request_id": "failure-test-001",
    }
    assert private_error not in response.text
