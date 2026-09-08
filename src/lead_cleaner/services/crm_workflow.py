"""Durable, reviewed-version CRM handoff. Unknown writes are reconciled, never blindly replayed."""

import hashlib
from datetime import UTC, datetime
from typing import Any

from lead_cleaner.schemas.crm import NotionSyncResponse
from lead_cleaner.schemas.lead import LeadProcessingResult
from lead_cleaner.services.conversation_store import (
    ConversationStore,
    ConversationMessageProcessingError,
)
from lead_cleaner.services.notion_crm import NotionCrmWriter, NotionCrmUnavailableError


def sync_reviewed(
    store: ConversationStore,
    writer: NotionCrmWriter,
    *,
    result: LeadProcessingResult,
    draft: str | None,
    operator: str,
    version: str,
) -> NotionSyncResponse:
    lead_id = result.cleaned_lead.lead_id
    job_id = "crm_" + hashlib.sha256(f"{writer.data_source_id}:{version}".encode()).hexdigest()
    lock_id = "crm_" + hashlib.sha256(f"{writer.data_source_id}:{lead_id}".encode()).hexdigest()
    payload: dict[str, Any]
    with store.processing_lease(lock_id):
        event = store.get_event(job_id)
        if event:
            payload = event["payload"]
            if payload["state"] == "synced":
                return NotionSyncResponse.model_validate(payload["response"])
            if datetime.now(UTC).timestamp() < payload.get("retry_not_before", 0):
                raise ConversationMessageProcessingError(
                    "CRM retry is scheduled; wait before retrying."
                )
            found = writer.reconcile(lead_id, job_id)
            if found:
                store.update_event(
                    job_id,
                    {**payload, "state": "synced", "response": found.model_dump(mode="json")},
                )
                return found
            raise ConversationMessageProcessingError(
                "CRM write outcome is unknown. Check Notion before creating another record."
            )
        payload = {
            "state": "processing",
            "version": version,
            "operator": operator,
            "analysis": result.model_dump(mode="json"),
            "approved_draft": draft,
        }
        store.put_event("crm_sync", operator, payload, event_id=job_id)
        try:
            response = writer.write(
                result,
                operator_name=operator,
                approved_followup_email=draft,
                update_existing=True,
                sync_version=job_id,
            )
        except Exception as error:
            store.update_event(
                job_id,
                {
                    **payload,
                    "state": "unknown",
                    "error_type": type(error).__name__,
                    "retry_not_before": datetime.now(UTC).timestamp()
                    + (error.retry_after if isinstance(error, NotionCrmUnavailableError) else 0),
                },
            )
            raise
        store.update_event(
            job_id, {**payload, "state": "synced", "response": response.model_dump(mode="json")}
        )
        return response
