from lead_cleaner.config import AppMode
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
    )

    assert result.cleaned_lead.email == "invalid-email"
    assert result.validation_result.is_valid is False
    assert result.validation_result.error_codes == ["invalid_email_format"]
    assert result.analysis_result is None
    assert result.sources == []
