from lead_cleaner.schemas.ai_output import (
    AnalysisMetadata,
    AnalysisMethod,
    LeadAnalysisResult,
)
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import LeadDecision, LeadFeatures, SecuritySignals
from lead_cleaner.services.ai_analysis import extract_lead_features_with_llm
from lead_cleaner.services.lead_feature_merger import (
    merge_extracted_features_with_server_facts,
)
from lead_cleaner.services.llm_client import LLMClientError
from lead_cleaner.services.policy_v1 import evaluate_policy
from lead_cleaner.services.prompt_builder import FEATURE_PROMPT_VERSION
from lead_cleaner.services.rule_feature_extractor import extract_rule_features
from lead_cleaner.services.security_signal_detector import detect_security_signals


def build_analysis_result(
    features: LeadFeatures,
    security_signals: SecuritySignals,
    decision: LeadDecision,
    analysis_method: AnalysisMethod,
    fallback_reason: str | None = None,
) -> LeadAnalysisResult:
    """Build the public result without flattening or hiding policy evidence."""

    if analysis_method == "llm_features":
        summary = (
            "Analysis generated from constrained LLM-extracted features and the "
            "deterministic lead policy."
        )
    else:
        summary = (
            "Analysis generated from deterministic rule-extracted features and the "
            "deterministic lead policy."
        )

    return LeadAnalysisResult(
        features=features,
        security_signals=security_signals,
        decision=decision,
        lead_summary=summary,
        recommended_action="Review this lead manually before taking follow-up action.",
        followup_email_draft="",
        metadata=AnalysisMetadata(
            analysis_method=analysis_method,
            recommendation_method="generic_template",
            retrieval_method="skipped",
            prompt_version=(FEATURE_PROMPT_VERSION if analysis_method == "llm_features" else None),
            fallback_reason=fallback_reason,
        ),
    )


def build_policy_analysis(
    features: LeadFeatures,
    security_signals: SecuritySignals,
    analysis_method: AnalysisMethod,
    fallback_reason: str | None = None,
) -> LeadAnalysisResult:
    decision = evaluate_policy(features, security_signals)
    return build_analysis_result(
        features,
        security_signals,
        decision,
        analysis_method,
        fallback_reason,
    )


def build_rule_fallback_analysis(cleaned_lead: CleanedLead) -> LeadAnalysisResult:
    security_signals = detect_security_signals(cleaned_lead.message)
    features = extract_rule_features(cleaned_lead)
    return build_policy_analysis(features, security_signals, "rule_features")


def analyze_lead(cleaned_lead: CleanedLead) -> LeadAnalysisResult:
    security_signals = detect_security_signals(cleaned_lead.message)

    try:
        extracted_features = extract_lead_features_with_llm(cleaned_lead)
        features = merge_extracted_features_with_server_facts(
            extracted_features,
            cleaned_lead,
        )
        analysis_method: AnalysisMethod = "llm_features"
        fallback_reason: str | None = None
    except LLMClientError as error:
        print(f"[LLM_FALLBACK] LLM failed, using rule fallback: {error}")
        features = extract_rule_features(cleaned_lead)
        analysis_method = "rule_features"
        fallback_reason = "llm_client_error"

    return build_policy_analysis(
        features,
        security_signals,
        analysis_method,
        fallback_reason,
    )
