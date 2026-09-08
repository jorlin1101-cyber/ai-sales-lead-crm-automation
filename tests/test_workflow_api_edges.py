import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from lead_cleaner.schemas.crm import NotionSyncResponse
from lead_cleaner.schemas.conversation import ConversationMessageRequest
from tests.test_conversations import make_client, message_payload
from tests.test_workflow_regressions import demo_app, post
from tests.test_api_lifecycle import VALID_PAYLOAD


def test_reviewed_conversation_crm_uses_snapshot_and_blocks_stale_version(tmp_path):
    with make_client(tmp_path) as client:
        writer = Mock(data_source_id="workflow-edge")
        writer.write.return_value = NotionSyncResponse(
            status="created", lead_id="test", page_id="p1", synced_at=datetime.now(UTC)
        )
        client.app.state.notion_crm_writer = writer
        result = post(client, "1", "8个人想去川西").json()
        cid = result["conversation_id"]
        draft = result["reply_draft"]
        url = f"/crm/notion/conversations/{cid}"
        payload = {"draft_id": draft["draft_id"], "expected_version": 1}
        assert client.post(url, json=payload).status_code == 409
        assert (
            client.post(
                f"/conversations/{cid}/drafts/{draft['draft_id']}/review",
                json={"expected_version": 1, "action": "approve", "body_text": "Reviewed snapshot"},
            ).status_code
            == 200
        )
        assert client.post(url, json=payload).status_code == 409
        payload["expected_version"] = 2
        assert client.post(url, json=payload).status_code == 200
        assert client.post(url, json=payload).status_code == 200
        assert writer.write.call_count == 1
        assert writer.write.call_args.kwargs["approved_followup_email"] == "Reviewed snapshot"
        post(client, "2", "人数改成12个人")
        assert client.post(url, json=payload).status_code == 409
        client.app.state.notion_crm_writer = None
        assert client.post(url, json=payload).status_code == 503


def test_single_crm_rejects_missing_and_changed_analysis(tmp_path):
    with make_client(tmp_path) as client:
        writer = Mock(data_source_id="workflow-edge")
        client.app.state.notion_crm_writer = writer
        payload = {
            "raw_lead": VALID_PAYLOAD,
            "confirmed": True,
            "source_authorized": True,
            "operator_name": "spoofed",
        }
        assert client.post("/crm/notion/leads", json=payload).status_code == 409
        payload["analysis_id"] = client.post("/process-lead", json=VALID_PAYLOAD).json()[
            "analysis_id"
        ]
        payload["raw_lead"] = {**VALID_PAYLOAD, "message": "Different customer input"}
        assert client.post("/crm/notion/leads", json=payload).status_code == 409
        writer.write.assert_not_called()


def test_quote_api_records_rule_and_refuses_conflicts(tmp_path):
    rules = tmp_path / "prices.json"
    rules.write_text(
        json.dumps(
            [
                {
                    "rule_id": "fixture",
                    "version": "v1",
                    "product": "fixture",
                    "hotel_tier": "4",
                    "currency": "CNY",
                    "valid_from": "2020-01-01",
                    "valid_until": "2099-12-31",
                    "per_person": "100",
                    "included": ["fixture only"],
                    "assumptions": ["synthetic price, not for customers"],
                }
            ]
        ),
        encoding="utf8",
    )
    with make_client(tmp_path) as client:
        client.app.state.settings.pricing_rules_path = rules
        cid = post(client, "1", "8个人想去川西").json()["conversation_id"]
        payload = {
            "product": "fixture",
            "travel_date": "2090-10-03",
            "group_size": 8,
            "hotel_tier": "4",
            "currency": "CNY",
        }
        assert client.post("/conversations/nonexistent/quote", json=payload).status_code == 404
        response = client.post(f"/conversations/{cid}/quote", json=payload)
        assert response.status_code == 200
        assert response.json()["total"] == "800.00"
        assert (
            client.app.state.conversation_service.store.get_event(response.json()["quote_id"])[
                "kind"
            ]
            == "quote"
        )
        assert (
            client.post(
                f"/conversations/{cid}/quote", json={**payload, "group_size": 9}
            ).status_code
            == 409
        )
        post(client, "2", "12个人")
        assert client.post(f"/conversations/{cid}/quote", json=payload).status_code == 409


@pytest.mark.parametrize("size,status", [("invalid", 400), ("-1", 400), ("70000", 413)])
def test_invalid_request_sizes_are_client_errors(tmp_path, size, status):
    with make_client(tmp_path) as client:
        assert (
            client.post(
                "/conversations/messages", content="{}", headers={"Content-Length": size}
            ).status_code
            == status
        )


def test_signed_invalid_payload_returns_422_and_disabled_returns_404(tmp_path):
    with make_client(tmp_path) as client:
        assert client.post("/webhooks/inbound", content="{}").status_code == 404
    secret = "test-secret"
    with TestClient(demo_app(tmp_path, inbound_webhook_secret=secret)) as client:
        stamp = str(int(time.time()))
        body = b"{}"
        signature = hmac.new(
            secret.encode(), stamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        assert (
            client.post(
                "/webhooks/inbound",
                content=body,
                headers={"x-leadflow-timestamp": stamp, "x-leadflow-signature": signature},
            ).status_code
            == 422
        )


def test_guest_cannot_record_external_send_or_quote(tmp_path):
    with TestClient(demo_app(tmp_path)) as client:
        result = post(client, "1", "8个人").json()
        cid = result["conversation_id"]
        draft = result["reply_draft"]
        assert (
            client.post(
                f"/conversations/{cid}/drafts/{draft['draft_id']}/review",
                json={"expected_version": 1, "action": "record_sent", "external_receipt": "fake"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/conversations/{cid}/quote",
                json={
                    "product": "test",
                    "travel_date": "2090-10-03",
                    "group_size": 8,
                    "hotel_tier": "4",
                    "currency": "CNY",
                },
            ).status_code
            == 403
        )


def test_readiness_and_missing_draft_errors(tmp_path):
    with make_client(tmp_path) as client:
        store = client.app.state.conversation_service.store
        with patch.object(store.engine, "connect", side_effect=RuntimeError("offline database")):
            assert client.get("/ready").status_code == 503
        cid = post(client, "1", "8个人").json()["conversation_id"]
        assert (
            client.post(
                f"/conversations/{cid}/drafts/nonexistent/review",
                json={"action": "approve", "expected_version": 1},
            ).status_code
            == 422
        )
        request = message_payload("empty-bootstrap", "hello", channel="web_chat")
        request["external_conversation_id"] = "empty-bootstrap"
        empty = store.get_or_create_conversation(ConversationMessageRequest(**request))
        assert client.get(f"/conversations/{empty.conversation_id}/latest").status_code == 404


@pytest.mark.parametrize(
    "channel,message",
    [
        ("email", "Please explain Sichuan private tour pricing for 8 people."),
        ("web_chat", "What is included in the Sichuan private tour?"),
    ],
)
def test_english_grounded_reply_uses_channel_and_citations(tmp_path, channel, message):
    from lead_cleaner.api.main import create_app
    from lead_cleaner.config import Settings

    with TestClient(
        create_app(
            settings=Settings(
                _env_file=None,
                app_mode="rule_only",
                allow_network=False,
                rag_backend="keyword_rrf",
                conversation_db_path=tmp_path / "english.sqlite",
            )
        )
    ) as client:
        payload = message_payload("english-1", message, channel=channel)
        payload["sender_name"] = "Lina"
        payload["subject"] = "Sichuan inquiry" if channel == "email" else None
        result = client.post("/conversations/messages", json=payload)
        assert result.status_code == 200
        draft = result.json()["reply_draft"]
        assert draft["generation_method"] == "rag_grounded_template"
        assert draft["source_ids"]
        assert all(
            item["text"] and item["sha256"] == hashlib.sha256(item["text"].encode()).hexdigest()
            for item in draft["evidence"]
        )
        if channel == "email":
            assert draft["subject"] == "Re: Sichuan inquiry"
            assert "Best regards" in draft["body_text"]
        else:
            assert draft["subject"] is None and "Best regards" not in draft["body_text"]


@pytest.mark.parametrize(
    "overrides", [{"service_access_mode": "protected"}, {"service_access_token": "short"}]
)
def test_invalid_operator_configuration_fails_closed(overrides):
    from lead_cleaner.config import Settings

    with pytest.raises(ValueError):
        Settings(_env_file=None, **overrides)
