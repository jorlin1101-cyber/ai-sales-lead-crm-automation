from pathlib import Path

from fastapi.testclient import TestClient

from lead_cleaner.api.main import create_app
from lead_cleaner.config import AppMode, RagBackend, Settings
from lead_cleaner.services.rule_feature_extractor import extract_group_size


def make_client(tmp_path, *, rag_backend: RagBackend = RagBackend.DISABLED):
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.RULE_ONLY,
        allow_network=False,
        rag_backend=rag_backend,
        rag_required=rag_backend != RagBackend.DISABLED,
        knowledge_chunks_path=Path("data/knowledge_snapshot/knowledge_chunks.json"),
        conversation_db_path=tmp_path / "conversations.sqlite3",
    )
    return TestClient(create_app(settings=settings))


def message_payload(message_id: str, text: str, *, channel: str = "email") -> dict:
    return {
        "channel": channel,
        "source": "gmail" if channel == "email" else "website_chat",
        "external_conversation_id": "customer-thread-001",
        "external_message_id": message_id,
        "sender_name": "李明",
        "sender_email": "li.ming@example.com",
        "company_name": "成都行远旅行社",
        "subject": "川西行程咨询" if channel == "email" else None,
        "message": text,
        "source_authorized": True,
    }


def test_email_conversation_carries_facts_and_deduplicates(tmp_path):
    assert extract_group_size("我们有8个人想去川西")[0] == 8
    with make_client(tmp_path) as client:
        first = client.post(
            "/conversations/messages",
            json=message_payload("msg-1", "我们有8个人想去川西，想了解价格。"),
        )
        assert first.status_code == 200
        first_data = first.json()
        assert first_data["turn_number"] == 1
        assert first_data["reply_draft"]["channel"] == "email"
        assert first_data["reply_draft"]["subject"].startswith("Re:")
        assert "出行日期" in first_data["open_questions"]

        duplicate = client.post(
            "/conversations/messages",
            json=message_payload("msg-1", "我们有8个人想去川西，想了解价格。"),
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["idempotency_status"] == "duplicate"
        assert duplicate.json()["turn_number"] == 1

        reused_with_different_content = client.post(
            "/conversations/messages",
            json=message_payload("msg-1", "这不是第一条消息的原始内容。"),
        )
        assert reused_with_different_content.status_code == 409
        assert reused_with_different_content.json()["detail"]["code"] == ("idempotency_key_reused")

        second = client.post(
            "/conversations/messages",
            json=message_payload("msg-2", "日期是10月3日到7日，预算每人5000元，没有特殊需求。"),
        )
        assert second.status_code == 200
        second_data = second.json()
        assert second_data["turn_number"] == 2
        facts = {fact["key"]: fact for fact in second_data["confirmed_facts"]}
        assert facts["group_size"]["value"] == "8"
        assert facts["travel_date"]["value"] == "10月3日到7日"
        assert facts["budget"]["value"] == "预算每人5000元"
        assert second_data["open_questions"] == ["酒店等级"]
        assert "Subject:" not in second_data["reply_draft"]["body_text"]
        assert "酒店等级" in second_data["reply_draft"]["body_text"]

        conversation_id = first_data["conversation_id"]
        summary = client.get(f"/conversations/{conversation_id}")
        timeline = client.get(f"/conversations/{conversation_id}/timeline")
        assert summary.status_code == 200
        assert summary.json()["turn_number"] == 2
        assert timeline.status_code == 200
        assert [item["turn_number"] for item in timeline.json()] == [1, 2]
        assert all(item["reply_text_preview"] for item in timeline.json())


def test_explicit_correction_updates_current_fact_and_preserves_history(tmp_path):
    with make_client(tmp_path) as client:
        first = client.post(
            "/conversations/messages",
            json=message_payload("msg-1", "8个人计划去川西。", channel="web_chat"),
        )
        second = client.post(
            "/conversations/messages",
            json=message_payload("msg-2", "人数改成12个人。", channel="web_chat"),
        )
        assert first.status_code == 200
        assert second.status_code == 200
        data = second.json()
        # This fixture disables RAG; missing evidence requires review, not a fact conflict.
        assert data["state"] == "needs_human_review"
        assert data["requires_human_review"] is True
        group_fact = next(fact for fact in data["confirmed_facts"] if fact["key"] == "group_size")
        assert group_fact["status"] == "customer_confirmed"
        assert group_fact["value"] == "12"
        assert data["reply_draft"]["channel"] == "web_chat"
        assert data["reply_draft"]["subject"] is None


def test_social_dm_uses_short_reply_without_email_subject(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post(
            "/conversations/messages",
            json=message_payload(
                "dm-1",
                "We have a group of 6 and need a private Sichuan quotation.",
                channel="social_dm",
            ),
        )
        assert response.status_code == 200
        draft = response.json()["reply_draft"]
        assert draft["channel"] == "social_dm"
        assert draft["subject"] is None
        assert "Subject:" not in draft["body_text"]
        assert len(draft["open_questions"]) > 1
        assert draft["open_questions"][1] not in draft["body_text"]


def test_contextual_rag_uses_confirmed_history_and_persists_evidence(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        first = client.post(
            "/conversations/messages",
            json=message_payload("rag-1", "我们有8个人想去川西，请介绍行程和报价。"),
        )
        assert first.status_code == 200
        first_data = first.json()
        assert first_data["retrieval"]["decision"] == "required"
        assert first_data["retrieval"]["retrieval_method"] == "keyword_rrf"
        assert 1 <= len(first_data["retrieval"]["sources"]) <= 3

        second = client.post(
            "/conversations/messages",
            json=message_payload("rag-2", "日期是10月3日，预算每人5000元。"),
        )
        assert second.status_code == 200
        second_data = second.json()
        assert any("group_size: 8" in query for query in second_data["retrieval"]["queries"])
        assert any("10月3日" in query for query in second_data["retrieval"]["queries"])

        timeline = client.get(f"/conversations/{second_data['conversation_id']}/timeline").json()
        assert timeline[-1]["source_count"] == len(second_data["reply_draft"]["source_ids"])
        assert set(second_data["reply_draft"]["source_ids"]).issubset(
            {source["chunk_id"] for source in second_data["retrieval"]["sources"]}
        )


def test_acknowledgement_skips_rag_but_still_generates_reply(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        response = client.post(
            "/conversations/messages",
            json=message_payload("ack-1", "好的，谢谢。", channel="web_chat"),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["retrieval"] == {
            "decision": "skipped",
            "reason": "acknowledgement",
            "queries": [],
            "retrieval_method": "skipped",
            "sources": [],
        }
        assert data["reply_draft"]["body_text"]


def test_web_chat_without_email_still_analyzes_the_message(tmp_path):
    payload = message_payload("anonymous-chat-1", "我们有8个人想去川西。", channel="web_chat")
    payload["sender_email"] = None
    with make_client(tmp_path) as client:
        response = client.post("/conversations/messages", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["current_analysis"]["validation_result"]["is_valid"] is True
        assert any(fact["key"] == "group_size" for fact in data["confirmed_facts"])


def test_conversation_continues_after_application_restart(tmp_path):
    first_payload = message_payload("restart-1", "我们有8个人想去川西。")
    with make_client(tmp_path) as client:
        first = client.post("/conversations/messages", json=first_payload)
        assert first.status_code == 200
        conversation_id = first.json()["conversation_id"]

    with make_client(tmp_path) as restarted_client:
        second = restarted_client.post(
            "/conversations/messages",
            json=message_payload("restart-2", "日期是10月3日，预算每人5000元。"),
        )
        assert second.status_code == 200
        data = second.json()
        assert data["conversation_id"] == conversation_id
        assert data["turn_number"] == 2
        assert any(
            fact["key"] == "group_size" and fact["value"] == "8" for fact in data["confirmed_facts"]
        )


def test_product_question_is_answered_from_retrieved_product_content(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        response = client.post(
            "/conversations/messages",
            json=message_payload(
                "product-1",
                "请介绍川西私人定制产品，包括路线和时长。",
                channel="web_chat",
            ),
        )
        assert response.status_code == 200
        data = response.json()
        draft = data["reply_draft"]
        assert draft["generation_method"] == "rag_grounded_template"
        assert "itinerary" in draft["answer_intents"]
        assert "8天7晚" in draft["body_text"]
        assert "成都—康定—理塘—稻城—亚丁" in draft["body_text"]
        assert draft["source_ids"]


def test_pricing_question_explains_rules_without_inventing_a_quote(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        response = client.post(
            "/conversations/messages",
            json=message_payload(
                "pricing-1",
                "8个人去川西，报价规则是什么，大概多少钱？",
                channel="web_chat",
            ),
        )
        assert response.status_code == 200
        data = response.json()
        body = data["reply_draft"]["body_text"]
        assert "没有适用于所有行程的固定金额" in body
        assert "销售顾问核对资源后将提供明细报价" in body
        assert "不会编造" not in body
        assert "酒店" in body
        assert any(
            source["source_title"] == "Private Tour Pricing Rules"
            for source in data["retrieval"]["sources"]
        )
        assert "hotel_tier" not in {fact["key"] for fact in data["confirmed_facts"]}
        assert "酒店等级" in data["open_questions"]


def test_permit_and_payment_question_returns_operational_rules(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        response = client.post(
            "/conversations/messages",
            json=message_payload(
                "permit-1",
                "去西藏需要什么证件，定金和付款规则是什么？",
                channel="web_chat",
            ),
        )
        assert response.status_code == 200
        data = response.json()
        body = data["reply_draft"]["body_text"]
        assert "入藏" in body
        assert "10—14个工作日" in body
        assert "30%" in body
        assert all(
            source_id in {source["chunk_id"] for source in data["retrieval"]["sources"]}
            for source_id in data["reply_draft"]["source_ids"]
        )


def test_second_turn_uses_saved_context_for_grounded_pricing_reply(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        first = client.post(
            "/conversations/messages",
            json=message_payload("multi-rag-1", "我们有8个人计划去川西。", channel="web_chat"),
        )
        assert first.status_code == 200
        second = client.post(
            "/conversations/messages",
            json=message_payload(
                "multi-rag-2",
                "那报价规则是什么？",
                channel="web_chat",
            ),
        )
        assert second.status_code == 200
        data = second.json()
        assert data["turn_number"] == 2
        assert "同行人数：8" in data["reply_draft"]["body_text"]
        assert any("group_size: 8" in query for query in data["retrieval"]["queries"])
        assert data["reply_draft"]["generation_method"] == "rag_grounded_template"


def test_disabled_rag_uses_context_template_without_false_citations(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.DISABLED) as client:
        response = client.post(
            "/conversations/messages",
            json=message_payload(
                "no-rag-1",
                "请介绍川西私人定制产品。",
                channel="web_chat",
            ),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["reply_draft"]["generation_method"] == "context_template"
        assert data["reply_draft"]["source_ids"] == []
        assert data["retrieval"]["sources"] == []
