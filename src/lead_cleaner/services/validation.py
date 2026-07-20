from pydantic import EmailStr, TypeAdapter, ValidationError

from lead_cleaner.schemas.lead import (
    CleanedLead,
    LeadValidationResult,
    ValidationErrorCode,
)


_EMAIL_ADAPTER = TypeAdapter(EmailStr)


def validate_lead(cleaned_lead: CleanedLead) -> LeadValidationResult:
    """
    验证清洗后的 lead 是否符合基本要求。
    """
    error_codes: list[ValidationErrorCode] = []

    if not cleaned_lead.email:
        error_codes.append("empty_email")
    else:
        try:
            _EMAIL_ADAPTER.validate_python(cleaned_lead.email)
        except ValidationError:
            error_codes.append("invalid_email_format")

    if not cleaned_lead.message:
        error_codes.append("empty_message_after_cleaning")

    return LeadValidationResult(
        is_valid=not error_codes,
        error_codes=error_codes,
    )
