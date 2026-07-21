from lead_cleaner.config import AppMode
from lead_cleaner.schemas.lead import KnowledgeSource
from lead_cleaner.schemas.policy import LeadFeatures, SecuritySignals
from lead_cleaner.services.feature_extractor import FeatureExtractionOutcome
from lead_cleaner.services.lead_analyzer import build_policy_analysis
from lead_cleaner.services.recommendation_builder import build_recommendation


def make_analysis(
    *,
    execution_mode: AppMode = AppMode.RULE_ONLY,
    customer_kind: str = "agency",
    spam: bool = False,
    injection: bool = False,
):
    outcome = FeatureExtractionOutcome(
        features=LeadFeatures(
            customer_kind=customer_kind,
            contains_spam_or_promotion=spam,
            company_name_present=True,
            cleaned_message_length=100,
        ),
        execution_mode=execution_mode,
        analysis_method=("demo_fixture" if execution_mode == AppMode.DEMO else "rule_features"),
    )
    return build_policy_analysis(
        outcome,
        SecuritySignals(injection_suspected=injection),
    )


def make_source() -> KnowledgeSource:
    return KnowledgeSource(
        chunk_id="chunk-1",
        source_title="Pricing Rules",
        section="Pricing Variables",
        rank=1,
    )


def test_demo_with_sources_uses_deterministic_grounded_template() -> None:
    recommendation = build_recommendation(
        make_analysis(execution_mode=AppMode.DEMO),
        [make_source()],
        "keyword_rrf",
    )

    assert recommendation.recommendation_method == "demo_template"
    assert "Pricing Rules — Pricing Variables" in recommendation.recommended_action
    assert recommendation.followup_email_draft == ""


def test_rule_only_with_sources_stays_generic() -> None:
    recommendation = build_recommendation(
        make_analysis(),
        [make_source()],
        "keyword_rrf",
    )

    assert recommendation.recommendation_method == "generic_template"
    assert "Pricing Rules" not in recommendation.recommended_action


def test_injection_suspected_never_claims_llm_grounded_generation() -> None:
    recommendation = build_recommendation(
        make_analysis(execution_mode=AppMode.DEMO, injection=True),
        [make_source()],
        "keyword_rrf",
    )

    assert recommendation.recommendation_method != "llm_grounded"


def test_spam_skips_recommendation() -> None:
    recommendation = build_recommendation(
        make_analysis(spam=True),
        [],
        "skipped",
    )

    assert recommendation.recommendation_method == "skipped"
    assert "Do not send" in recommendation.recommended_action
