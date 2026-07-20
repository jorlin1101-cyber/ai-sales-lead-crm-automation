from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import ExtractedLeadFeatures, LeadFeatures
from lead_cleaner.services.rule_feature_extractor import extract_rule_features


def merge_extracted_features_with_server_facts(
    extracted_features: ExtractedLeadFeatures,
    cleaned_lead: CleanedLead,
) -> LeadFeatures:
    """Build canonical policy input without trusting an LLM for server-owned facts.

    The rule extractor remains the single source of truth for deterministic conflict
    detection. Its business classifications do not overwrite the extracted features.
    """

    rule_features = extract_rule_features(cleaned_lead)

    return LeadFeatures.model_validate(
        {
            **extracted_features.model_dump(),
            "company_name_present": rule_features.company_name_present,
            "cleaned_message_length": rule_features.cleaned_message_length,
            "conflict_codes": list(rule_features.conflict_codes),
        }
    )
