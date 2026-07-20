from fastapi.testclient import TestClient

from lead_cleaner.api.main import app
from lead_cleaner.schemas.policy import LeadFeatures, SecuritySignals
from lead_cleaner.services import processor
from lead_cleaner.services.lead_analyzer import build_policy_analysis

client = TestClient(app)


def test_health_check():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_process_lead_valid_lead(monkeypatch):
    def fake_analyze_lead(cleaned_lead):
        return build_policy_analysis(
            LeadFeatures(
                customer_kind="agency",
                group_size=20,
                asks_for_price=True,
                requests_private_or_custom_service=True,
                company_name_present=True,
                cleaned_message_length=len(cleaned_lead.message),
            ),
            SecuritySignals(),
            "rule_features",
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
    assert data["analysis_result"]["features"]["customer_kind"] == "agency"
    assert data["analysis_result"]["decision"]["lead_type"] == "B2B"
    assert data["analysis_result"]["decision"]["lead_subtype"] == "Agency"
    assert data["analysis_result"]["decision"]["intent_level"] == "High"
    assert data["analysis_result"]["metadata"]["analysis_method"] == "rule_features"
    assert data["analysis_result"]["security_signals"] == {
        "injection_suspected": False,
        "matched_pattern_codes": [],
        "knowledge_injection_suspected": False,
    }
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

    analysis_properties = schemas["LeadAnalysisResult"]["properties"]

    assert set(analysis_properties) == {
        "features",
        "security_signals",
        "decision",
        "lead_summary",
        "recommended_action",
        "followup_email_draft",
        "metadata",
    }
    assert "lead_score" not in analysis_properties
    assert "analysis_method" not in analysis_properties

    metadata_properties = schemas["AnalysisMetadata"]["properties"]

    assert "analysis_method" in metadata_properties
    assert "fallback_reason" in metadata_properties

    decision_properties = schemas["LeadDecision"]["properties"]

    assert "lead_score" in decision_properties
    assert "score_breakdown" in decision_properties
    assert "policy_version" in decision_properties

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
