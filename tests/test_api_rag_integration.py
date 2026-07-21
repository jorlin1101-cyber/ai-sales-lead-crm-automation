from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lead_cleaner.api import main as api_main
from lead_cleaner.api.main import create_app
from lead_cleaner.config import AppMode, RagBackend, Settings
from lead_cleaner.rag.retriever import RagUnavailableError


VALID_DEMO_PAYLOAD = {
    "external_lead_id": "sample-lead-001",
    "name": "Demo Lead",
    "email": "demo@example.com",
    "company_name": "Example Travel Agency",
    "message": "We need a private Chengdu tour.",
    "source": "Website",
}


def test_process_lead_returns_real_sanitized_top_three_sources() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.DEMO,
        allow_network=False,
        rag_backend=RagBackend.KEYWORD_RRF,
        rag_required=True,
        demo_feature_fixtures_path=Path("data/demo/lead_feature_fixtures.json"),
        knowledge_chunks_path=Path("data/knowledge_snapshot/knowledge_chunks.json"),
    )

    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/process-lead", json=VALID_DEMO_PAYLOAD)

    assert response.status_code == 200
    payload = response.json()
    sources = payload["sources"]
    assert 1 <= len(sources) <= 3
    assert [source["rank"] for source in sources] == list(range(1, len(sources) + 1))
    assert all(set(source) == {"chunk_id", "source_title", "section", "rank"} for source in sources)
    metadata = payload["analysis_result"]["metadata"]
    assert metadata["retrieval_method"] == "keyword_rrf"
    assert metadata["recommendation_method"] == "demo_template"


def test_optional_missing_snapshot_keeps_api_available(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.RULE_ONLY,
        rag_backend=RagBackend.KEYWORD_RRF,
        rag_required=False,
        knowledge_chunks_path=tmp_path / "missing.json",
    )

    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/process-lead", json=VALID_DEMO_PAYLOAD)

    assert response.status_code == 200
    payload = response.json()
    assert payload["sources"] == []
    assert payload["analysis_result"]["metadata"]["retrieval_method"] == "unavailable"
    assert payload["analysis_result"]["metadata"]["recommendation_method"] == ("generic_template")


def test_required_missing_snapshot_fails_during_startup(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.RULE_ONLY,
        rag_backend=RagBackend.KEYWORD_RRF,
        rag_required=True,
        knowledge_chunks_path=tmp_path / "missing.json",
    )

    with pytest.raises(RagUnavailableError, match="failed to start"):
        with TestClient(create_app(settings=settings)):
            pass


def test_required_runtime_rag_error_returns_safe_503(monkeypatch) -> None:
    class RaisingRetriever:
        def retrieve(self, query: str):
            raise RagUnavailableError("private backend details")

    monkeypatch.setattr(
        api_main,
        "create_rag_retriever",
        lambda settings: RaisingRetriever(),
    )
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.RULE_ONLY,
        rag_backend=RagBackend.DISABLED,
    )

    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/process-lead", json=VALID_DEMO_PAYLOAD)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rag_unavailable"
    assert "private backend details" not in response.text
