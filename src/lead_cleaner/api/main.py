from fastapi import FastAPI

from lead_cleaner.schemas.lead import LeadProcessingResult, RawLeadInput
from lead_cleaner.services.processor import process_lead


app = FastAPI(
    title="AI Sales Lead Cleaner API",
    version="0.1.0",
)

@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}

@app.post("/process-lead", response_model=LeadProcessingResult)
def process_lead_api(raw_lead: RawLeadInput) -> LeadProcessingResult:
    return process_lead(raw_lead)


