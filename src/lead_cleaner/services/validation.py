from lead_cleaner.schemas.lead import CleanedLead, LeadValidationResult


def validate_lead(cleaned_lead: CleanedLead) -> LeadValidationResult:
    """
    验证清洗后的 lead 是否符合基本要求。
    """
    if not cleaned_lead.email:
        return LeadValidationResult(
            is_valid=False,
            error_reason="empty_email",
        )
    if "@" not in cleaned_lead.email or "." not in cleaned_lead.email:
        return LeadValidationResult(
            is_valid=False,
            error_reason="invalid_email_format",
        )
    if not cleaned_lead.message:
        return LeadValidationResult(
            is_valid=False,
            error_reason="empty_message",
        )
    return LeadValidationResult(
        is_valid=True,
        error_reason="valid",
    )
