from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from lead_cleaner.api.main import create_app
from lead_cleaner.config import AppMode, RagBackend, Settings


@pytest.fixture
def demo_client() -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.DEMO,
        allow_network=False,
        rag_backend=RagBackend.DISABLED,
    )

    with TestClient(create_app(settings=settings)) as client:
        yield client


@pytest.mark.parametrize(
    ("payload", "expected_score", "expected_intent", "expected_disposition"),
    [
        (
            {
                "external_lead_id": "n8n-demo-high-001",
                "name": "Demo High Lead",
                "email": "high@example.com",
                "company_name": "Example Travel Agency",
                "message": ("Please quote a private Chengdu tour for 20 travelers in September."),
                "source": "n8n-demo",
            },
            100,
            "High",
            "qualified",
        ),
        (
            {
                "external_lead_id": "n8n-demo-medium-001",
                "name": "Demo Medium Lead",
                "email": "medium@example.com",
                "company_name": "",
                "message": "I am considering a private Chengdu trip next year.",
                "source": "n8n-demo",
            },
            59,
            "Medium",
            "nurture",
        ),
        (
            {
                "external_lead_id": "n8n-demo-low-001",
                "name": "Demo Low Lead",
                "email": "low@example.com",
                "company_name": "",
                "message": "Please send general travel information.",
                "source": "n8n-demo",
            },
            14,
            "Low",
            "manual_review",
        ),
    ],
)
def test_valid_demo_leads_produce_stable_routing_decisions(
    demo_client: TestClient,
    payload: dict[str, str],
    expected_score: int,
    expected_intent: str,
    expected_disposition: str,
) -> None:
    response = demo_client.post("/process-lead", json=payload)

    assert response.status_code == 200
    data = response.json()
    analysis = data["analysis_result"]

    assert data["cleaned_lead"]["external_lead_id"] == payload["external_lead_id"]
    assert data["validation_result"] == {"is_valid": True, "error_codes": []}
    assert analysis is not None
    assert analysis["decision"]["lead_score"] == expected_score
    assert analysis["decision"]["intent_level"] == expected_intent
    assert analysis["decision"]["disposition"] == expected_disposition
    assert analysis["metadata"]["execution_mode"] == "demo"
    assert analysis["metadata"]["analysis_method"] == "demo_fixture"
    assert analysis["metadata"]["fallback_reason"] is None


def test_invalid_demo_lead_skips_analysis_and_routes_as_invalid(
    demo_client: TestClient,
) -> None:
    payload = {
        "external_lead_id": "n8n-demo-invalid-001",
        "name": "Demo Invalid Lead",
        "email": "invalid-email",
        "company_name": "",
        "message": "Please send information.",
        "source": "n8n-demo",
    }

    response = demo_client.post("/process-lead", json=payload)

    assert response.status_code == 200
    data = response.json()

    assert data["cleaned_lead"]["external_lead_id"] == payload["external_lead_id"]
    assert data["validation_result"]["is_valid"] is False
    assert data["validation_result"]["error_codes"] == ["invalid_email_format"]
    assert data["analysis_result"] is None
    assert data["sources"] == []
