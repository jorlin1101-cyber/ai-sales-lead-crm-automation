from uuid import uuid4
from lead_cleaner.schemas.lead import CleanedLead, RawLeadInput


def clean_lead(raw_lead: RawLeadInput) -> CleanedLead:
    lead_id = str(uuid4())
    name = (raw_lead.name or "").strip()
    email = raw_lead.email.strip().lower()
    company_name = (raw_lead.company_name or "").strip()
    message = raw_lead.message.strip()
    source = raw_lead.source.strip() or "Unknown"
    return CleanedLead(
        lead_id=lead_id,
        name=name,
        email=email,
        company_name=company_name,
        message=message,
        source=source,
    )
