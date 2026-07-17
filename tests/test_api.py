from fastapi.testclient import TestClient

from lead_cleaner.api.main import app
from lead_cleaner.schemas.ai_output import LeadAnalysisResult
from lead_cleaner.services import processor

client = TestClient(app)


def test_health_check():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_process_lead_valid_lead(monkeypatch):
    def fake_analyze_lead(cleaned_lead):
        return LeadAnalysisResult(
            lead_type="B2B",
            lead_subtype="Agency",
            intent_level="High",
            lead_score=88,
            lead_summary="A high-value agency lead asking for a private China tour.",
            recommended_action="Review the lead and prepare a tailored follow-up.",
            followup_email_draft="Thank you for your inquiry. We would be happy to discuss your China itinerary.",
            analysis_method="rule_fallback",
            confidence=0.55,
        )

    monkeypatch.setattr(
        processor,
        "analyze_lead",
        fake_analyze_lead,
    )

    payload = {
        "name": "John Doe",
        "email": "john@example.com",
        "company_name": "Spain Travel Agency",
        "message": (
            "We want a quotation for a 20 people private tour to China in September."
        ),
        "source": "Website",
    }

    response = client.post("/process-lead", json=payload)

    assert response.status_code == 200

    data = response.json()

    assert data["cleaned_lead"]["email"] == "john@example.com"
    assert data["validation_result"]["is_valid"] is True
    assert data["validation_result"]["error_reason"] == "valid"
    assert data["analysis_result"] is not None
    assert data["analysis_result"]["lead_type"] == "B2B"
    assert data["analysis_result"]["lead_subtype"] == "Agency"
    assert data["analysis_result"]["intent_level"] == "High"
    assert data["analysis_result"]["analysis_method"] == "rule_fallback"


def test_process_lead_invalid_email_skips_analysis():
    payload = {
        "name": "Bad Lead",
        "email": "invalid-email",
        "company_name": "Example Corp",
        "message": "I am interested in your product.",
        "source": "Website",
    }

    response = client.post("/process-lead", json=payload)

    assert response.status_code == 200

    data = response.json()

    assert data["validation_result"]["is_valid"] is False
    assert data["validation_result"]["error_reason"] == "invalid_email_format"
    assert data["analysis_result"] is None


def test_process_lead_missing_email_returns_422():
    payload = {
        "name": "No Email",
        "company_name": "Example Corp",
        "message": "I am interested in your product.",
        "source": "Website",
    }

    response = client.post("/process-lead", json=payload)

    assert response.status_code == 422
