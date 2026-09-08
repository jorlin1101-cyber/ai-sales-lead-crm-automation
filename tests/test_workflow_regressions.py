from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from lead_cleaner.api.main import create_app
from lead_cleaner.config import Settings, RagBackend
from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.conversation import ConversationFact
from lead_cleaner.services.conversation_store import (
    ConversationMessageProcessingError,
    conversation_facts,
    conversation_fact_history,
    conversation_messages,
    conversation_leases,
    analysis_runs,
    reply_drafts,
)
from lead_cleaner.services.conversation_reply_composer import (
    _knowledge_bullets,
    _missing_quote_details,
)
from lead_cleaner.services.quotation import QuoteInput, estimate_quote
from tests.test_conversations import make_client, message_payload


def post(client, mid, text, **overrides):
    payload = message_payload(mid, text, channel="web_chat")
    payload.update(overrides)
    return client.post("/conversations/messages", json=payload)


def test_ack_preserves_opportunity_and_reports_message_score(tmp_path):
    with make_client(tmp_path) as client:
        first = post(
            client, "1", "我们有12个人，计划10月3日去川西，希望包车定制行程，请提供报价和可用日期。"
        ).json()
        second = post(client, "2", "好的，谢谢。").json()
        assert (
            second["current_analysis"]["analysis_result"]["decision"]["lead_score"]
            >= first["current_analysis"]["analysis_result"]["decision"]["lead_score"]
        )
        assert (
            second["message_score"]
            < second["current_analysis"]["analysis_result"]["decision"]["lead_score"]
        )
        assert second["retrieval"]["decision"] == "skipped"


@pytest.mark.parametrize(
    "changes",
    [
        {"external_conversation_id": "different"},
        {"sender_email": "different@example.com"},
        {"sender_name": "Different"},
        {"company_name": "Different"},
        {"message": "Different message"},
    ],
)
def test_message_identity_conflicts_return_409(tmp_path, changes):
    with make_client(tmp_path) as client:
        assert post(client, "1", "8个人想去川西").status_code == 200
        payload = message_payload("1", "8个人想去川西", channel="web_chat")
        payload.update(changes)
        assert client.post("/conversations/messages", json=payload).status_code == 409


def test_channel_accounts_are_distinct(tmp_path):
    with make_client(tmp_path) as client:
        one = post(client, "1", "8个人想去川西", account_id="a").json()
        two = post(client, "1", "8个人想去川西", account_id="b").json()
        assert one["conversation_id"] != two["conversation_id"]


def test_failed_message_recovers_same_turn_without_partial_facts(tmp_path):
    with make_client(tmp_path) as client:
        store = client.app.state.conversation_service.store
        with patch.object(store, "save_turn", side_effect=RuntimeError("synthetic crash")):
            with pytest.raises(RuntimeError):
                post(client, "1", "8个人想去川西")
        with store.engine.connect() as connection:
            assert (
                connection.execute(select(conversation_messages.c.processing_status)).scalar_one()
                == "failed"
            )
            assert connection.execute(select(conversation_facts)).first() is None
        assert post(client, "2", "新的消息").status_code == 409
        result = post(client, "1", "8个人想去川西")
        assert result.status_code == 200
        assert result.json()["turn_number"] == 1
        assert post(client, "1", "8个人想去川西").json()["idempotency_status"] == "duplicate"
        with store.engine.connect() as connection:
            assert len(connection.execute(select(analysis_runs)).all()) == 1
            assert len(connection.execute(select(reply_drafts)).all()) == 1


def test_expired_lease_is_fenced_and_active_lease_rejects_concurrency(tmp_path):
    with make_client(tmp_path) as client:
        cid = post(client, "1", "8个人想去川西").json()["conversation_id"]
        store = client.app.state.conversation_service.store
        with store.processing_lease(cid) as stale:
            assert post(client, "2", "日期10月3日").status_code == 409
            with store.engine.begin() as connection:
                connection.execute(
                    update(conversation_leases).values(
                        expires_at=datetime.now(UTC) - timedelta(seconds=1)
                    )
                )
            with store.processing_lease(cid) as current:
                with store.engine.begin() as connection:
                    store.assert_lease(connection, cid, current)
                    with pytest.raises(ConversationMessageProcessingError):
                        store.assert_lease(connection, cid, stale)
        assert post(client, "2", "日期10月3日").status_code == 200


def test_correction_preserves_history_and_unexplained_change_conflicts(tmp_path):
    with make_client(tmp_path) as client:
        post(client, "1", "8个人想去川西")
        corrected = post(client, "2", "人数改成12个人。").json()
        assert (
            next(f["value"] for f in corrected["confirmed_facts"] if f["key"] == "group_size")
            == "12"
        )
        store = client.app.state.conversation_service.store
        with store.engine.connect() as connection:
            history = (
                connection.execute(
                    select(conversation_fact_history.c.fact_value).where(
                        conversation_fact_history.c.fact_key == "group_size"
                    )
                )
                .scalars()
                .all()
            )
        assert history == ["8", "12"]
        conflict = post(client, "3", "9个人").json()
        assert conflict["requires_human_review"]


@pytest.mark.parametrize("language", ["zh", "en"])
def test_source_revision_changes_invalidate_old_translation(language):
    source = json.loads(
        Path("data/knowledge_snapshot/knowledge_chunks.json").read_text(encoding="utf-8")
    )
    original = next(
        c
        for c in source
        if c["source_title"] == "Travel Permit and Payment FAQ"
        and c["section"] == "Common Questions"
    )
    chunk = RetrievedChunk.model_validate(
        {
            **original,
            "score": 1,
            "rank": 1,
            "retrieval_source": "fusion",
            "text": "# New payment rules\n- Deposit is 50%; balance due 7 days before arrival.",
        }
    )
    text = " ".join(_knowledge_bullets(chunk, language))
    assert "50%" in text and "30%" not in text and "14天" not in text


def test_new_chinese_source_and_known_hotel_are_not_excluded():
    chunk = RetrievedChunk(
        chunk_id="new",
        source_type="notion_page",
        notion_page_id="new",
        source_title="新产品",
        source_path="new",
        doc_type="product",
        region="general",
        section="新章节",
        text="新产品定金为50%。",
        score=1,
        rank=1,
        retrieval_source="fusion",
    )
    assert _knowledge_bullets(chunk, "zh") == ["新产品定金为50%。"]
    fact = ConversationFact(
        key="hotel_tier",
        value="四星",
        status="customer_confirmed",
        confidence=1,
        source_message_id="1",
    )
    assert not any("酒店" in s for s in _missing_quote_details([fact], "zh"))


@pytest.mark.parametrize(
    "message",
    [
        "Buy backlinks and SEO services, limited offer. 请介绍川西产品和报价。",
        "不要再联系我，退订。",
        "Unsubscribe, do not contact me.",
    ],
)
def test_suppressed_turn_never_retrieves_or_generates_a_sendable_draft(tmp_path, message):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        with patch.object(
            client.app.state.rag_retriever,
            "retrieve",
            side_effect=AssertionError("must not retrieve"),
        ):
            result = post(client, "1", message).json()
        assert result["state"] == "do_not_contact"
        assert result["reply_draft"]["status"] == "suppressed"
        assert result["reply_draft"]["body_text"] == ""
        assert result["retrieval"]["decision"] == "blocked"
        assert post(client, "2", "请给我报价").json()["reply_draft"]["status"] == "suppressed"


def test_draft_approval_versions_sent_history_and_stale_reviews(tmp_path):
    with make_client(tmp_path) as client:
        result = post(client, "1", "8个人想去川西").json()
        cid, draft = result["conversation_id"], result["reply_draft"]
        url = f"/conversations/{cid}/drafts/{draft['draft_id']}/review"
        approved = client.post(
            url,
            json={
                "action": "approve",
                "expected_version": 1,
                "body_text": "人工核对后的两个方案。",
            },
        )
        assert approved.status_code == 200 and approved.json()["draft_version"] == 2
        assert client.post(url, json={"action": "save", "expected_version": 1}).status_code == 409
        assert (
            client.post(url, json={"action": "record_sent", "expected_version": 2}).status_code
            == 422
        )
        assert (
            client.post(
                url,
                json={
                    "action": "record_sent",
                    "expected_version": 2,
                    "external_receipt": "provider-123",
                },
            ).status_code
            == 200
        )
        store = client.app.state.conversation_service.store
        assert any("人工核对后的两个方案" in s for s in store.get_recent_messages(cid))
        assert client.get(f"/conversations/{cid}/latest").json()["reply_draft"]["status"] == "sent"
        timeline = client.get(f"/conversations/{cid}/timeline").json()
        assert timeline[0]["reply_text"] == "人工核对后的两个方案。"
        assert client.get("/conversations").json()[0]["conversation_id"] == cid
        second = post(client, "2", "日期10月3日").json()
        second_url = f"/conversations/{cid}/drafts/{second['reply_draft']['draft_id']}/review"
        post(client, "3", "酒店四星")
        assert (
            client.post(second_url, json={"action": "approve", "expected_version": 1}).status_code
            == 409
        )


def demo_app(tmp_path, **extra):
    return create_app(
        settings=Settings(
            _env_file=None,
            rag_backend="disabled",
            app_mode="rule_only",
            conversation_db_path=tmp_path / "demo.sqlite",
            service_access_mode="public_demo",
            **extra,
        )
    )


def test_visitors_are_isolated_and_cannot_write_external_crm(tmp_path):
    app = demo_app(tmp_path)
    with TestClient(app) as first, TestClient(app) as second:
        one = post(first, "1", "8个人想去川西").json()
        two = post(second, "1", "8个人想去川西").json()
        assert one["conversation_id"] != two["conversation_id"]
        cid = one["conversation_id"]
        assert second.get(f"/conversations/{cid}/latest").status_code == 404
        assert len(second.get("/conversations").json()) == 1
        assert second.post("/crm/notion/leads", json={}).status_code == 403
        assert first.get("/session").json()["role"] == "guest"
        for _ in range(19):
            assert post(first, "1", "8个人想去川西").status_code == 200
        assert post(first, "2", "新消息").status_code == 429


def test_operator_token_protected_mode_and_csrf(tmp_path):
    settings = Settings(
        _env_file=None,
        rag_backend="disabled",
        conversation_db_path=tmp_path / "auth.sqlite",
        service_access_mode="protected",
        service_access_token="a" * 32,
    )
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/conversations").status_code == 401
        client.headers["Authorization"] = "Bearer " + "a" * 32
        assert client.get("/ready").status_code == 200
        assert (
            client.post(
                "/conversations/messages",
                headers={"Origin": "https://attacker.invalid"},
                json=message_payload("1", "8个人"),
            ).status_code
            == 403
        )


def test_signed_channel_adapter_verifies_signature_and_deduplicates(tmp_path):
    secret = "sample-webhook-secret"
    with TestClient(demo_app(tmp_path, inbound_webhook_secret=secret)) as client:
        body = json.dumps(message_payload("provider-1", "8个人想去川西")).encode()
        stamp = str(int(time.time()))
        headers = {"x-leadflow-timestamp": stamp, "Content-Type": "application/json"}
        assert client.post("/webhooks/inbound", content=body, headers=headers).status_code == 401
        headers["x-leadflow-signature"] = hmac.new(
            secret.encode(), stamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        one = client.post("/webhooks/inbound", content=body, headers=headers)
        assert one.status_code == 200
        assert (
            client.post("/webhooks/inbound", content=body, headers=headers).json()[
                "idempotency_status"
            ]
            == "duplicate"
        )
        headers["x-leadflow-timestamp"] = "1"
        assert client.post("/webhooks/inbound", content=body, headers=headers).status_code == 401


def test_quote_requires_real_rules_and_calculates_decimal_totals(tmp_path):
    from datetime import date

    request = QuoteInput(
        product="sample", travel_date="2030-10-03", group_size=8, hotel_tier="4", currency="CNY"
    )
    with pytest.raises(ValueError, match="No verified"):
        estimate_quote(request, None, today=date(2030, 10, 1))
    rules = [
        {
            "rule_id": "sample",
            "version": "v1",
            "product": "sample",
            "hotel_tier": "4",
            "currency": "CNY",
            "valid_from": "2030-01-01",
            "valid_until": "2030-12-31",
            "per_person": "100.15",
            "fixed_group_cost": "50",
            "tax_rate": "0.06",
            "included": ["test"],
            "assumptions": ["fixture only"],
        }
    ]
    path = tmp_path / "prices.json"
    path.write_text(json.dumps(rules), encoding="utf-8")
    quote = estimate_quote(request, path, today=date(2030, 10, 1))
    assert quote["total"] == "902.27" and quote["valid_until"] == "2030-10-03"
    rules.append(rules[0])
    path.write_text(json.dumps(rules), encoding="utf-8")
    with pytest.raises(ValueError, match="overlapping"):
        estimate_quote(request, path, today=date(2030, 10, 1))
