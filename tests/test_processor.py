from lead_cleaner.config import AppMode
from lead_cleaner.rag.retriever import RagRetrievalOutcome
from lead_cleaner.schemas.lead import CleanedLead, RawLeadInput
from lead_cleaner.schemas.policy import LeadFeatures
from lead_cleaner.services.feature_extractor import FeatureExtractionOutcome
from lead_cleaner.services.processor import process_lead


class StubFeatureExtractor:
    def __init__(self, outcome: FeatureExtractionOutcome) -> None:
        self.outcome = outcome
        self.calls: list[CleanedLead] = []

    def extract(self, cleaned_lead: CleanedLead) -> FeatureExtractionOutcome:
        self.calls.append(cleaned_lead)
        return self.outcome


class FailIfCalledFeatureExtractor:
    def extract(self, cleaned_lead: CleanedLead) -> FeatureExtractionOutcome:
        raise AssertionError("Invalid leads must skip feature extraction")


class StubRagRetriever:
    def __init__(self, outcome: RagRetrievalOutcome) -> None:
        self.outcome = outcome
        self.queries: list[str] = []

    def retrieve(self, query: str) -> RagRetrievalOutcome:
        self.queries.append(query)
        return self.outcome


class FailIfCalledRagRetriever:
    def retrieve(self, query: str) -> RagRetrievalOutcome:
        raise AssertionError("This lead must skip RAG")


def test_process_lead_valid_lead_uses_safe_rule_only_default():
    raw_lead = RawLeadInput(
        name="John Doe",
        email="john@example.com",
        company_name="Spain Travel Agency",
        message="We want a quotation for a 20 people private tour to China in September.",
        source="Website",
    )

    result = process_lead(raw_lead)

    assert result.cleaned_lead.email == "john@example.com"
    assert result.validation_result.is_valid is True
    assert result.validation_result.error_codes == []
    assert result.analysis_result is not None
    assert result.analysis_result.decision.lead_type == "B2B"
    assert result.analysis_result.decision.lead_subtype == "Agency"
    assert result.analysis_result.decision.intent_level == "High"
    assert result.analysis_result.metadata.execution_mode == "rule_only"
    assert result.analysis_result.metadata.analysis_method == "rule_features"
    assert result.sources == []


def test_process_lead_uses_injected_feature_extractor():
    raw_lead = RawLeadInput(
        external_lead_id="sample-lead-001",
        name="John Doe",
        email="john@example.com",
        company_name="Spain Travel Agency",
        message="We want a private tour.",
        source="Website",
    )
    extractor = StubFeatureExtractor(
        FeatureExtractionOutcome(
            features=LeadFeatures(
                customer_kind="agency",
                asks_for_price=True,
                company_name_present=True,
                cleaned_message_length=len(raw_lead.message),
            ),
            execution_mode=AppMode.DEMO,
            analysis_method="demo_fixture",
        )
    )

    result = process_lead(raw_lead, feature_extractor=extractor)

    assert result.analysis_result is not None
    assert result.analysis_result.metadata.execution_mode == "demo"
    assert result.analysis_result.metadata.analysis_method == "demo_fixture"
    assert extractor.calls == [result.cleaned_lead]


def test_process_lead_invalid_lead_skips_feature_extraction():
    raw_lead = RawLeadInput(
        name="John Doe",
        email="invalid-email",
        company_name="Example Corp",
        message="I am interested in your product.",
        source="Website",
    )

    result = process_lead(
        raw_lead,
        feature_extractor=FailIfCalledFeatureExtractor(),
        rag_retriever=FailIfCalledRagRetriever(),
    )

    assert result.cleaned_lead.email == "invalid-email"
    assert result.validation_result.is_valid is False
    assert result.validation_result.error_codes == ["invalid_email_format"]
    assert result.analysis_result is None
    assert result.sources == []


def test_process_lead_spam_skips_rag() -> None:
    raw_lead = RawLeadInput(
        email="spam@example.com",
        message="Buy followers now. Click this promotional offer.",
    )
    extractor = StubFeatureExtractor(
        FeatureExtractionOutcome(
            features=LeadFeatures(
                customer_kind="unknown",
                contains_spam_or_promotion=True,
                cleaned_message_length=len(raw_lead.message),
            ),
            execution_mode=AppMode.RULE_ONLY,
            analysis_method="rule_features",
        )
    )

    result = process_lead(
        raw_lead,
        feature_extractor=extractor,
        rag_retriever=FailIfCalledRagRetriever(),
    )

    assert result.analysis_result is not None
    assert result.analysis_result.decision.disposition == "spam"
    assert result.analysis_result.metadata.retrieval_method == "skipped"
    assert result.sources == []


def test_rag_availability_does_not_change_decision() -> None:
    raw_lead = RawLeadInput(
        email="agency@example.com",
        company_name="Example Travel Agency",
        message="We need a private tour quotation for 20 people.",
    )
    feature_outcome = FeatureExtractionOutcome(
        features=LeadFeatures(
            customer_kind="agency",
            group_size=20,
            asks_for_price=True,
            requests_private_or_custom_service=True,
            company_name_present=True,
            cleaned_message_length=len(raw_lead.message),
        ),
        execution_mode=AppMode.RULE_ONLY,
        analysis_method="rule_features",
    )
    available_retriever = StubRagRetriever(RagRetrievalOutcome(retrieval_method="keyword_rrf"))
    unavailable_retriever = StubRagRetriever(
        RagRetrievalOutcome(
            retrieval_method="unavailable",
            failure_reason="retrieval_failure",
        )
    )

    with_rag = process_lead(
        raw_lead,
        feature_extractor=StubFeatureExtractor(feature_outcome),
        rag_retriever=available_retriever,
    )
    without_rag = process_lead(
        raw_lead,
        feature_extractor=StubFeatureExtractor(feature_outcome),
        rag_retriever=unavailable_retriever,
    )

    assert with_rag.analysis_result is not None
    assert without_rag.analysis_result is not None
    assert with_rag.analysis_result.decision == without_rag.analysis_result.decision
    assert with_rag.analysis_result.metadata.retrieval_method == "keyword_rrf"
    assert without_rag.analysis_result.metadata.retrieval_method == "unavailable"
