from uuid import NAMESPACE_URL, uuid4, uuid5
from lead_cleaner.schemas.lead import CleanedLead, RawLeadInput


def clean_lead(raw_lead: RawLeadInput) -> CleanedLead:
    name = (raw_lead.name or "").strip()
    email = raw_lead.email.strip().lower()
    company_name = (raw_lead.company_name or "").strip()
    message = raw_lead.message.strip()
    source = (raw_lead.source or "").strip() or "Unknown"
    external_lead_id = (raw_lead.external_lead_id or "").strip() or None
    lead_id = (
        str(uuid5(NAMESPACE_URL, f"{source.casefold()}:{external_lead_id}"))
        if external_lead_id is not None
        else str(uuid4())
    )
    return CleanedLead(
        lead_id=lead_id,
        external_lead_id=external_lead_id,
        name=name,
        email=email,
        company_name=company_name,
        message=message,
        source=source,
    )
