from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import ExtractedLeadFeatures
from lead_cleaner.services.llm_client import call_openai_structured_feature_extraction
from lead_cleaner.services.prompt_builder import (
    FeaturePromptLanguage,
    build_lead_feature_prompt,
    get_lead_feature_system_prompt,
)


def extract_lead_features_with_llm(
    cleaned_lead: CleanedLead,
    language: FeaturePromptLanguage = "en",
) -> ExtractedLeadFeatures:
    """Extract constrained business facts without asking the LLM to score the lead."""

    system_prompt = get_lead_feature_system_prompt(language)
    user_prompt = build_lead_feature_prompt(cleaned_lead, language=language)

    return call_openai_structured_feature_extraction(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
