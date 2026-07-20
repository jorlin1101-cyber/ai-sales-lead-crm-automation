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
        "external_lead_id": "website-form-001",
        "name": "John Doe",
        "email": "john@example.com",
        "company_name": "Spain Travel Agency",
        "message": ("We want a quotation for a 20 people private tour to China in September."),
        "source": "Website",
    }

    response = client.post("/process-lead", json=payload)

    assert response.status_code == 200

    data = response.json()

    assert data["cleaned_lead"]["external_lead_id"] == "website-form-001"
    assert data["cleaned_lead"]["email"] == "john@example.com"
    assert data["validation_result"]["is_valid"] is True
    assert data["validation_result"]["error_codes"] == []
    assert data["analysis_result"] is not None
    assert data["analysis_result"]["lead_type"] == "B2B"
    assert data["analysis_result"]["lead_subtype"] == "Agency"
    assert data["analysis_result"]["intent_level"] == "High"
    assert data["analysis_result"]["analysis_method"] == "rule_fallback"
    assert data["sources"] == []


def test_process_lead_invalid_email_skips_analysis(monkeypatch):
    def fail_if_analysis_is_called(cleaned_lead):
        raise AssertionError("analyze_lead must not be called for an invalid lead")

    monkeypatch.setattr(
        processor,
        "analyze_lead",
        fail_if_analysis_is_called,
    )

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
    assert data["validation_result"]["error_codes"] == ["invalid_email_format"]
    assert data["analysis_result"] is None
    assert data["sources"] == []


def test_process_lead_empty_email_returns_domain_invalid():
    payload = {
        "email": "",
        "message": "I need a private tour.",
    }

    response = client.post("/process-lead", json=payload)

    assert response.status_code == 200

    data = response.json()

    assert data["validation_result"]["is_valid"] is False
    assert data["validation_result"]["error_codes"] == ["empty_email"]
    assert data["analysis_result"] is None
    assert data["sources"] == []


def test_process_lead_whitespace_message_returns_domain_invalid():
    payload = {
        "email": "john@example.com",
        "message": "   ",
    }

    response = client.post("/process-lead", json=payload)

    assert response.status_code == 200

    data = response.json()

    assert data["validation_result"]["is_valid"] is False
    assert data["validation_result"]["error_codes"] == ["empty_message_after_cleaning"]
    assert data["analysis_result"] is None
    assert data["sources"] == []


def test_process_lead_empty_message_returns_422():
    payload = {
        "email": "john@example.com",
        "message": "",
    }

    response = client.post("/process-lead", json=payload)

    assert response.status_code == 422


def test_process_lead_unknown_company_field_returns_422():
    payload = {
        "email": "john@example.com",
        "message": "I need a private tour.",
        "company": "ABC Travel",
    }

    response = client.post("/process-lead", json=payload)

    assert response.status_code == 422

    errors = response.json()["detail"]

    assert any(
        error["type"] == "extra_forbidden" and error["loc"] == ["body", "company"]
        for error in errors
    )


def test_process_lead_missing_email_returns_422():
    payload = {
        "name": "No Email",
        "company_name": "Example Corp",
        "message": "I am interested in your product.",
        "source": "Website",
    }

    response = client.post("/process-lead", json=payload)

    assert response.status_code == 422


def test_openapi_schema_matches_lead_contract_v2():
    openapi_schema = app.openapi()
    schemas = openapi_schema["components"]["schemas"]

    raw_lead_schema = schemas["RawLeadInput"]
    raw_properties = raw_lead_schema["properties"]

    assert raw_lead_schema["additionalProperties"] is False
    assert set(raw_lead_schema["required"]) == {"email", "message"}

    assert "external_lead_id" in raw_properties
    assert raw_properties["email"]["maxLength"] == 320
    assert raw_properties["message"]["minLength"] == 1
    assert raw_properties["message"]["maxLength"] == 5000

    validation_properties = schemas["LeadValidationResult"]["properties"]

    assert set(validation_properties) == {"is_valid", "error_codes"}
    assert "error_reason" not in validation_properties

    processing_properties = schemas["LeadProcessingResult"]["properties"]

    assert "sources" in processing_properties
    assert processing_properties["sources"]["type"] == "array"

    source_properties = schemas["KnowledgeSource"]["properties"]

    assert set(source_properties) == {
        "chunk_id",
        "source_title",
        "section",
        "rank",
    }
    assert source_properties["rank"]["minimum"] == 1
    assert source_properties["rank"]["maximum"] == 3

    response_schema = openapi_schema["paths"]["/process-lead"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]

    assert response_schema["$ref"] == ("#/components/schemas/LeadProcessingResult")
