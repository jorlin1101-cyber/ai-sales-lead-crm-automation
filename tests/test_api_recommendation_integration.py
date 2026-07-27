from fastapi.testclient import TestClient

from lead_cleaner.api import main as api_main
from lead_cleaner.api.main import create_app
from lead_cleaner.config import AppMode, Settings
from lead_cleaner.rag.retriever import RagRetrievalOutcome
from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import LeadFeatures
from lead_cleaner.services.feature_extractor import FeatureExtractionOutcome
from lead_cleaner.services.recommendation_generator import (
    GroundedRecommendationDraft,
)


class StubFeatureExtractor:
    def __init__(self) -> None:
        self.closed = False

    def extract(self, cleaned_lead: CleanedLead) -> FeatureExtractionOutcome:
        return FeatureExtractionOutcome(
            features=LeadFeatures(
                customer_kind="agency",
                group_size=20,
                asks_for_price=True,
                requests_private_or_custom_service=True,
                destinations=["Sichuan"],
                language="en",
                company_name_present=True,
                cleaned_message_length=len(cleaned_lead.message),
            ),
            execution_mode=AppMode.LIVE,
            analysis_method="rule_features",
            fallback_reason="timeout",
        )

    def close(self) -> None:
        self.closed = True


class StubRetriever:
    def __init__(self) -> None:
        self.closed = False

    def retrieve(self, query: str) -> RagRetrievalOutcome:
        return RagRetrievalOutcome(
            chunks=[
                RetrievedChunk(
                    chunk_id="chunk-1",
                    source_type="notion_page",
                    notion_page_id="private-page-id",
                    source_title="Sichuan Private Tour",
                    source_path="Private/Path",
                    doc_type="product",
                    region="western_sichuan",
                    product_name="Sichuan Private Tour",
                    section="Suitable For",
                    text="Suitable for private groups. Confirm dates before quoting.",
                    score=1.0,
                    rank=1,
                    retrieval_source="fusion",
                )
            ],
            retrieval_method="keyword_rrf",
        )

    def close(self) -> None:
        self.closed = True


class StubRecommendationGenerator:
    def __init__(self) -> None:
        self.closed = False
        self.call_count = 0

    def generate(self, *, cleaned_lead, analysis_result, chunks):
        self.call_count += 1
        return GroundedRecommendationDraft(
            recommended_action="Confirm travel dates before preparing the quotation.",
            followup_email_draft=(
                "Thank you for your inquiry. Could you confirm your preferred dates?"
            ),
            cited_chunk_ids=[chunks[0].chunk_id],
        )

    def close(self) -> None:
        self.closed = True


def test_api_lifecycle_injects_and_closes_grounded_recommendation_components(
    monkeypatch,
) -> None:
    feature_extractor = StubFeatureExtractor()
    rag_retriever = StubRetriever()
    recommendation_generator = StubRecommendationGenerator()

    monkeypatch.setattr(
        api_main,
        "create_feature_extractor",
        lambda settings: feature_extractor,
    )
    monkeypatch.setattr(
        api_main,
        "create_rag_retriever",
        lambda settings: rag_retriever,
    )
    monkeypatch.setattr(
        api_main,
        "create_recommendation_generator",
        lambda settings: recommendation_generator,
    )

    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        allow_network=True,
        openai_api_key="test-key",
        openai_model="test-model",
        grounded_recommendation_enabled=True,
    )
    payload = {
        "external_lead_id": "grounded-demo-001",
        "name": "Example Lead",
        "email": "lead@example.com",
        "company_name": "Example Travel Agency",
        "message": "We need a private Sichuan tour quotation for 20 people.",
        "source": "Website",
    }

    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/process-lead", json=payload)

        assert feature_extractor.closed is False
        assert rag_retriever.closed is False
        assert recommendation_generator.closed is False

    assert response.status_code == 200
    result = response.json()
    assert result["analysis_result"]["metadata"]["recommendation_method"] == "llm_grounded"
    assert result["analysis_result"]["followup_email_draft"].startswith("Thank you")
    assert result["sources"] == [
        {
            "chunk_id": "chunk-1",
            "source_title": "Sichuan Private Tour",
            "section": "Suitable For",
            "rank": 1,
        }
    ]
    assert recommendation_generator.call_count == 1
    assert feature_extractor.closed is True
    assert rag_retriever.closed is True
    assert recommendation_generator.closed is True
