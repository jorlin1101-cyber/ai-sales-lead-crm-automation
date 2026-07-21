from lead_cleaner.schemas.ai_output import (
    AnalysisMetadata,
    LeadAnalysisResult,
)
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import LeadDecision, SecuritySignals
from lead_cleaner.services.feature_extractor import (
    FeatureExtractionOutcome,
    FeatureExtractor,
)
from lead_cleaner.services.policy_v1 import evaluate_policy
from lead_cleaner.services.rule_feature_extractor import RuleFeatureExtractor
from lead_cleaner.services.security_signal_detector import detect_security_signals


def build_analysis_result(
    outcome: FeatureExtractionOutcome,
    security_signals: SecuritySignals,
    decision: LeadDecision,
) -> LeadAnalysisResult:
    """Build the public result from one validated extraction outcome."""

    if outcome.analysis_method == "llm_features":
        summary = (
            "Analysis generated from constrained LLM-extracted features and the "
            "deterministic lead policy."
        )
    elif outcome.analysis_method == "demo_fixture":
        summary = (
            "Analysis generated from an explicit offline demo fixture and the "
            "deterministic lead policy."
        )
    else:
        summary = (
            "Analysis generated from deterministic rule-extracted features and the "
            "deterministic lead policy."
        )

    return LeadAnalysisResult(
        features=outcome.features,
        security_signals=security_signals,
        decision=decision,
        lead_summary=summary,
        recommended_action="Review this lead manually before taking follow-up action.",
        followup_email_draft="",
        metadata=AnalysisMetadata(
            execution_mode=outcome.execution_mode.value,
            analysis_method=outcome.analysis_method,
            recommendation_method="generic_template",
            retrieval_method="skipped",
            provider=outcome.provider,
            model=outcome.model,
            prompt_version=outcome.prompt_version,
            fallback_reason=outcome.fallback_reason,
        ),
    )


def build_policy_analysis(
    outcome: FeatureExtractionOutcome,
    security_signals: SecuritySignals,
) -> LeadAnalysisResult:
    decision = evaluate_policy(outcome.features, security_signals)
    return build_analysis_result(outcome, security_signals, decision)


def build_rule_fallback_analysis(cleaned_lead: CleanedLead) -> LeadAnalysisResult:
    return analyze_lead(
        cleaned_lead,
        feature_extractor=RuleFeatureExtractor(),
    )


def analyze_lead(
    cleaned_lead: CleanedLead,
    *,
    feature_extractor: FeatureExtractor | None = None,
) -> LeadAnalysisResult:
    """Run security detection, feature extraction, and deterministic policy."""

    security_signals = detect_security_signals(cleaned_lead.message)
    extractor = feature_extractor or RuleFeatureExtractor()
    outcome = extractor.extract(cleaned_lead)

    return build_policy_analysis(outcome, security_signals)
