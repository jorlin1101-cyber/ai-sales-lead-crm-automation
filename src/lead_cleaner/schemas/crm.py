from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lead_cleaner.schemas.lead import RawLeadInput


class NotionSyncRequest(BaseModel):
    """A reviewed analysis result that may be written to the CRM."""

    model_config = ConfigDict(extra="forbid")

    raw_lead: RawLeadInput
    analysis_id: str | None = Field(default=None, max_length=100)
    confirmed: Literal[True]
    source_authorized: Literal[True]
    operator_name: str = Field(default="Sales reviewer", min_length=1, max_length=100)
    approved_followup_email: str | None = Field(default=None, max_length=5000)


class NotionSyncResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["created", "already_exists", "updated"]
    lead_id: str
    page_id: str
    page_url: str | None = None
    synced_at: datetime


class NotionCrmStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    connected: bool
    workspace_name: str | None = None
    data_source_title: str | None = None
    message: str
