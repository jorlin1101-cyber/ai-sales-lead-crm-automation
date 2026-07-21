import pytest
from pydantic import ValidationError

from lead_cleaner.schemas.ai_output import AnalysisMetadata, LeadAnalysisResult
from lead_cleaner.schemas.policy import (
    LeadDecision,
    LeadFeatures,
    ScoreComponent,
    SecuritySignals,
)


def make_decision() -> LeadDecision:
    return LeadDecision(
        lead_type="B2B",
        lead_subtype="Agency",
        disposition="qualified",
        intent_level="High",
        lead_score=90,
        score_breakdown=[
            ScoreComponent(
                component="customer_fit",
                points=30,
                max_points=30,
                reason_codes=["agency_customer"],
            ),
            ScoreComponent(
                component="intent_strength",
                points=30,
                max_points=30,
                reason_codes=["three_or_more_intent_signals"],
            ),
            ScoreComponent(
                component="order_value_proxy",
                points=25,
                max_points=25,
                reason_codes=["group_size_at_least_10"],
            ),
            ScoreComponent(
                component="information_completeness",
                points=5,
                max_points=15,
                reason_codes=["company_name_present"],
            ),
        ],
        needs_review=False,
        review_reasons=[],
        policy_version="policy-v1",
    )


def make_analysis_result() -> LeadAnalysisResult:
    return LeadAnalysisResult(
        features=LeadFeatures(
            customer_kind="agency",
            group_size=20,
            mentions_specific_dates=True,
            asks_for_price=True,
            requests_private_or_custom_service=True,
            destinations=["China"],
            language="en",
            company_name_present=True,
            cleaned_message_length=100,
        ),
        security_signals=SecuritySignals(),
        decision=make_decision(),
        lead_summary="A travel agency is asking for a China tour quotation.",
        recommended_action="Review the lead and prepare a tailored follow-up.",
        followup_email_draft="",
        metadata=AnalysisMetadata(
            execution_mode="live",
            analysis_method="llm_features",
            recommendation_method="generic_template",
            retrieval_method="skipped",
            provider="openai",
            model="test-model",
            prompt_version="lead-features-v1",
        ),
    )


def test_lead_analysis_result_keeps_features_security_decision_and_metadata_separate():
    result = make_analysis_result()

    assert result.features.customer_kind == "agency"
    assert result.security_signals.injection_suspected is False
    assert result.decision.lead_score == 90
    assert result.decision.policy_version == "policy-v1"
    assert result.metadata.analysis_method == "llm_features"
    assert result.metadata.prompt_version == "lead-features-v1"


def test_lead_analysis_result_serializes_nested_public_contract():
    payload = make_analysis_result().model_dump()

    assert set(payload) == {
        "features",
        "security_signals",
        "decision",
        "lead_summary",
        "recommended_action",
        "followup_email_draft",
        "metadata",
    }
    assert payload["decision"]["lead_score"] == 90
    assert "lead_score" not in payload
    assert "analysis_method" not in payload


def test_lead_analysis_result_rejects_old_flat_scoring_fields():
    payload = make_analysis_result().model_dump()
    payload["lead_score"] = 100

    with pytest.raises(ValidationError, match="extra_forbidden"):
        LeadAnalysisResult.model_validate(payload)


def test_analysis_metadata_accepts_rule_fallback_provenance():
    metadata = AnalysisMetadata(
        execution_mode="live",
        analysis_method="rule_features",
        recommendation_method="generic_template",
        retrieval_method="skipped",
        fallback_reason="timeout",
    )

    assert metadata.analysis_method == "rule_features"
    assert metadata.execution_mode == "live"
    assert metadata.fallback_reason == "timeout"
    assert metadata.provider is None


def test_analysis_metadata_rejects_invalid_analysis_method():
    with pytest.raises(ValidationError):
        AnalysisMetadata(
            execution_mode="live",
            analysis_method="llm",
            recommendation_method="generic_template",
            retrieval_method="skipped",
        )


@pytest.mark.parametrize("field", ["lead_summary", "recommended_action"])
def test_lead_analysis_result_rejects_empty_required_text(field: str):
    payload = make_analysis_result().model_dump()
    payload[field] = ""

    with pytest.raises(ValidationError):
        LeadAnalysisResult.model_validate(payload)
