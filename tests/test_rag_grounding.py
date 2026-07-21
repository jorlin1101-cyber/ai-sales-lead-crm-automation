from lead_cleaner.config import AppMode
from lead_cleaner.rag.retriever import RagRetrievalOutcome
from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import LeadFeatures, SecuritySignals
from lead_cleaner.services.feature_extractor import FeatureExtractionOutcome
from lead_cleaner.services.lead_analyzer import build_policy_analysis
from lead_cleaner.services.rag_grounding import ground_analysis_with_rag


class StubRetriever:
    def __init__(self, outcome: RagRetrievalOutcome) -> None:
        self.outcome = outcome
        self.queries: list[str] = []

    def retrieve(self, query: str) -> RagRetrievalOutcome:
        self.queries.append(query)
        return self.outcome


class FailIfCalledRetriever:
    def retrieve(self, query: str) -> RagRetrievalOutcome:
        raise AssertionError("Spam analysis must skip RAG")


def make_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="chunk-1",
        source_type="notion_page",
        notion_page_id="private-page-id",
        source_title="Private Tour Pricing Rules",
        source_path="Knowledge/Pricing",
        doc_type="pricing",
        region="general",
        product_name=None,
        section="Pricing Variables",
        text="Internal text",
        score=1.0,
        rank=1,
        retrieval_source="fusion",
    )


def make_analysis(*, spam: bool = False, execution_mode: AppMode = AppMode.RULE_ONLY):
    return build_policy_analysis(
        FeatureExtractionOutcome(
            features=LeadFeatures(
                customer_kind="agency",
                group_size=20,
                asks_for_price=True,
                requests_private_or_custom_service=True,
                contains_spam_or_promotion=spam,
                company_name_present=True,
                cleaned_message_length=100,
            ),
            execution_mode=execution_mode,
            analysis_method=("demo_fixture" if execution_mode == AppMode.DEMO else "rule_features"),
        ),
        SecuritySignals(),
    )


def make_cleaned_lead() -> CleanedLead:
    return CleanedLead(
        lead_id="lead-1",
        name="Example Lead",
        email="lead@example.com",
        company_name="Example Travel Agency",
        message="We need a private tour quotation for 20 people.",
        source="test",
    )


def test_grounding_adds_sanitized_sources_without_changing_decision() -> None:
    analysis = make_analysis(execution_mode=AppMode.DEMO)
    original_decision = analysis.decision.model_dump()
    retriever = StubRetriever(
        RagRetrievalOutcome(
            chunks=[make_chunk()],
            retrieval_method="keyword_rrf",
        )
    )

    grounded, sources = ground_analysis_with_rag(
        analysis,
        make_cleaned_lead(),
        rag_retriever=retriever,
    )

    assert grounded.decision.model_dump() == original_decision
    assert grounded.metadata.retrieval_method == "keyword_rrf"
    assert grounded.metadata.recommendation_method == "demo_template"
    assert [source.chunk_id for source in sources] == ["chunk-1"]
    assert retriever.queries == [
        "We need a private tour quotation for 20 people.",
        (
            "travel agency | group size 20 people | pricing quotation cost factors | "
            "private custom tour"
        ),
    ]


def test_unavailable_rag_keeps_decision_and_uses_generic_template() -> None:
    analysis = make_analysis()
    original_decision = analysis.decision.model_dump()
    retriever = StubRetriever(
        RagRetrievalOutcome(
            retrieval_method="unavailable",
            failure_reason="retrieval_failure",
        )
    )

    grounded, sources = ground_analysis_with_rag(
        analysis,
        make_cleaned_lead(),
        rag_retriever=retriever,
    )

    assert grounded.decision.model_dump() == original_decision
    assert grounded.metadata.retrieval_method == "unavailable"
    assert grounded.metadata.recommendation_method == "generic_template"
    assert sources == []


def test_no_retriever_is_truthfully_marked_disabled() -> None:
    grounded, sources = ground_analysis_with_rag(make_analysis(), make_cleaned_lead())

    assert grounded.metadata.retrieval_method == "disabled"
    assert sources == []


def test_spam_skips_rag() -> None:
    grounded, sources = ground_analysis_with_rag(
        make_analysis(spam=True),
        make_cleaned_lead(),
        rag_retriever=FailIfCalledRetriever(),
    )

    assert grounded.decision.disposition == "spam"
    assert grounded.metadata.retrieval_method == "skipped"
    assert grounded.metadata.recommendation_method == "skipped"
    assert sources == []
