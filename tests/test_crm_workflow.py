from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
import pytest

from lead_cleaner.schemas.crm import NotionSyncResponse
from lead_cleaner.services.conversation_store import (
    ConversationStore,
    ConversationMessageProcessingError,
)
from lead_cleaner.services.crm_workflow import sync_reviewed
from lead_cleaner.services.notion_crm import NotionCrmUnavailableError
from tests.test_notion_crm import _result, _schema, _writer


def test_sync_version_is_durable_and_never_written_twice(tmp_path):
    store = ConversationStore(tmp_path / "crm.sqlite3")
    writer = Mock(data_source_id="test-source")
    result = _result()
    writer.write.return_value = NotionSyncResponse(
        status="created",
        lead_id=result.cleaned_lead.lead_id,
        page_id="page1",
        synced_at=datetime.now(UTC),
    )
    kwargs = dict(result=result, draft="Reviewed draft", operator="operator", version="draft1:v2")
    first = sync_reviewed(store, writer, **kwargs)
    store.close()
    store = ConversationStore(tmp_path / "crm.sqlite3")
    try:
        assert sync_reviewed(store, writer, **kwargs) == first
        assert writer.write.call_count == 1
        assert writer.write.call_args.kwargs["approved_followup_email"] == "Reviewed draft"
        assert writer.write.call_args.kwargs["update_existing"] is True
    finally:
        store.close()


@pytest.mark.parametrize("found", [False, True])
def test_uncertain_sync_reads_marker_before_any_retry(tmp_path, found):
    store = ConversationStore(tmp_path / "crm.sqlite3")
    writer = Mock(data_source_id="test-source")
    result = _result()
    writer.write.side_effect = NotionCrmUnavailableError("response lost")
    kwargs = dict(result=result, draft="Reviewed", operator="operator", version="draft1:v1")
    try:
        with pytest.raises(NotionCrmUnavailableError):
            sync_reviewed(store, writer, **kwargs)
        writer.reconcile.return_value = (
            NotionSyncResponse(
                status="already_exists",
                lead_id=result.cleaned_lead.lead_id,
                page_id="page1",
                synced_at=datetime.now(UTC),
            )
            if found
            else None
        )
        if found:
            assert sync_reviewed(store, writer, **kwargs).page_id == "page1"
        else:
            with pytest.raises(ConversationMessageProcessingError, match="unknown"):
                sync_reviewed(store, writer, **kwargs)
        assert writer.write.call_count == 1
        writer.reconcile.assert_called_once()
    finally:
        store.close()


def test_retry_after_is_preserved_even_when_retries_exhausted():
    writer = _writer(lambda request: httpx.Response(429, headers={"Retry-After": "30"}, json={}))
    try:
        with pytest.raises(NotionCrmUnavailableError) as error:
            writer.status()
        assert error.value.retry_after == 30
    finally:
        writer.close()


def test_update_existing_keeps_sales_stage_and_appends_version():
    calls = []

    def handler(request):
        import json

        calls.append(
            (
                request.method,
                request.url.path,
                json.loads(request.content) if request.content else {},
            )
        )
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"results": [{"id": "page1"}]})
        if request.method == "GET":
            return httpx.Response(200, json=_schema())
        return httpx.Response(200, json={})

    writer = _writer(handler)
    try:
        assert (
            writer.write(
                _result(),
                operator_name="operator",
                approved_followup_email="Reviewed",
                update_existing=True,
                sync_version="v2",
            ).status
            == "updated"
        )
        patch = next(body for method, path, body in calls if path == "/v1/pages/page1")
        assert "状态" not in patch["properties"]
        children = next(
            body["children"] for method, path, body in calls if path.endswith("/children")
        )
        assert (
            "".join(item["text"]["content"] for item in children[-1]["paragraph"]["rich_text"])
            == "Sync Version: v2"
        )
    finally:
        writer.close()


def test_reconcile_follows_pages_and_requires_exact_marker():
    def handler(request):
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"results": [{"id": "page1"}]})
        if request.url.path.endswith("/children"):
            if "start_cursor" not in request.url.params:
                return httpx.Response(
                    200, json={"results": [], "has_more": True, "next_cursor": "next"}
                )
            return httpx.Response(
                200,
                json={
                    "results": [{"paragraph": {"rich_text": [{"plain_text": "Sync Version: v2"}]}}],
                    "has_more": False,
                },
            )
        return httpx.Response(200, json=_schema())

    writer = _writer(handler)
    try:
        assert writer.reconcile("lead1", "v2").page_id == "page1"
        assert writer.reconcile("lead1", "v1") is None
    finally:
        writer.close()
