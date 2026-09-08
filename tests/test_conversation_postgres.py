import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from lead_cleaner.schemas.conversation import ConversationMessageRequest
from lead_cleaner.services.conversation_store import ConversationStore


@pytest.mark.postgres
def test_postgresql_allocates_unique_turns_under_concurrency() -> None:
    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("Set TEST_POSTGRES_URL to run the PostgreSQL concurrency test.")

    external_conversation_id = f"postgres-test-{uuid4().hex}"
    request = ConversationMessageRequest(
        channel="web_chat",
        source="pytest",
        external_conversation_id=external_conversation_id,
        external_message_id="bootstrap",
        sender_name="并发测试",
        message="创建测试会话",
        source_authorized=True,
    )
    store = ConversationStore(database_url)
    try:
        conversation = store.get_or_create_conversation(request)

        def append(index: int) -> int:
            _, turn_number = store.append_message(
                conversation_id=conversation.conversation_id,
                external_message_id=f"{external_conversation_id}-{index}",
                channel="web_chat",
                source="pytest",
                subject=None,
                text=f"并发消息 {index}",
            )
            return turn_number

        with ThreadPoolExecutor(max_workers=4) as executor:
            turns = list(executor.map(append, range(1, 9)))

        assert sorted(turns) == list(range(1, 9))
    finally:
        store.close()


@pytest.mark.postgres
def test_postgresql_multiturn_recovery_and_review(tmp_path):
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from lead_cleaner.api.main import create_app
    from lead_cleaner.config import Settings
    from tests.test_conversations import message_payload

    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("Set TEST_POSTGRES_URL for PostgreSQL workflow verification.")
    settings = Settings(
        _env_file=None,
        app_mode="rule_only",
        allow_network=False,
        conversation_database_url=database_url,
        conversation_auto_create_schema=False,
    )
    thread = "pg-review-" + uuid4().hex
    with TestClient(create_app(settings=settings)) as client:
        store = client.app.state.conversation_service.store
        first = message_payload(
            thread + "-1", "8个人想去川西，请介绍行程和报价", channel="web_chat"
        )
        first["external_conversation_id"] = thread
        with patch.object(store, "save_turn", side_effect=RuntimeError("simulated crash")):
            with pytest.raises(RuntimeError):
                client.post("/conversations/messages", json=first)
        recovered = client.post("/conversations/messages", json=first)
        assert recovered.status_code == 200
        assert recovered.json()["turn_number"] == 1
        second = {**first, "external_message_id": thread + "-2", "message": "人数改成12个人"}
        current = client.post("/conversations/messages", json=second).json()
        assert current["turn_number"] == 2
        assert (
            next(f["value"] for f in current["confirmed_facts"] if f["key"] == "group_size") == "12"
        )
        cid = current["conversation_id"]
        draft = current["reply_draft"]
        url = f"/conversations/{cid}/drafts/{draft['draft_id']}/review"
        assert (
            client.post(url, json={"expected_version": 1, "action": "approve"}).status_code == 200
        )
        assert (
            client.post(url, json={"expected_version": 1, "action": "approve"}).status_code == 409
        )
        assert len(client.get(f"/conversations/{cid}/timeline").json()) == 2
