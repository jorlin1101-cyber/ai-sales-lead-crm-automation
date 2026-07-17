from lead_cleaner.schemas.ai_output import LeadAnalysisResult
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.services.llm_client import call_openai_structured_analysis
from lead_cleaner.services.prompt_builder import build_lead_analysis_prompt


def analyze_lead_with_llm(cleaned_lead: CleanedLead) -> LeadAnalysisResult:
    prompt = build_lead_analysis_prompt(cleaned_lead)

    analysis_result = call_openai_structured_analysis(prompt)

    return analysis_result
