from lead_cleaner.services.ai_analysis import analyze_lead_with_llm
from lead_cleaner.services.scoring import score_lead
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.ai_output import LeadAnalysisResult
from lead_cleaner.services.llm_client import LLMClientError


def build_rule_fallback_analysis(cleaned_lead: CleanedLead) -> LeadAnalysisResult:
    score_lead_result = score_lead(cleaned_lead)
    return LeadAnalysisResult(
        lead_type=score_lead_result.lead_type,
        lead_subtype=score_lead_result.lead_subtype,
        intent_level=score_lead_result.intent_level,
        lead_score=score_lead_result.lead_score,
        lead_summary=(
            "Rule-based fallback analysis generated from cleaned lead data because LLM analysis was unavailable."
        ),
        recommended_action="Review this lead manually before taking follow-up action.",
        followup_email_draft="",
        analysis_method="rule_fallback",
        confidence=0.5,
    )


def analyze_lead(cleaned_lead: CleanedLead) -> LeadAnalysisResult:
    try:
        return analyze_lead_with_llm(cleaned_lead)
    except LLMClientError as error:
        print(f"[LLM_FALLBACK] LLM failed, using rule fallback: {error}")
        return build_rule_fallback_analysis(cleaned_lead)
