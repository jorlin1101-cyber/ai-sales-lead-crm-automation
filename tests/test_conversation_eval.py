import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from lead_cleaner.api.main import create_app
from lead_cleaner.config import AppMode, RagBackend, Settings


EVAL_PATH = Path("data/evals/multi_turn_conversations.jsonl")


def _load_cases() -> list[dict]:
    return [json.loads(line) for line in EVAL_PATH.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["id"])
def test_multi_turn_business_reply_eval(case, tmp_path):
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.RULE_ONLY,
        allow_network=False,
        rag_backend=RagBackend.KEYWORD_RRF,
        rag_required=True,
        knowledge_chunks_path=Path("data/knowledge_snapshot/knowledge_chunks.json"),
        conversation_db_path=tmp_path / "conversation-eval.sqlite3",
    )
    conversation_key = f"eval-{case['id']}-{uuid4().hex}"
    response_data = None
    with TestClient(create_app(settings=settings)) as client:
        for turn_number, message in enumerate(case["turns"], start=1):
            payload = {
                "channel": case["channel"],
                "source": "offline_eval",
                "external_conversation_id": conversation_key,
                "external_message_id": f"{conversation_key}-{turn_number}",
                "sender_name": "脱敏评测客户",
                "sender_email": "eval@example.com",
                "company_name": None,
                "subject": "行程咨询" if case["channel"] == "email" else None,
                "message": message,
                "source_authorized": True,
            }
            response = client.post("/conversations/messages", json=payload)
            assert response.status_code == 200
            response_data = response.json()

    assert response_data is not None
    body = response_data["reply_draft"]["body_text"]
    for text in case["expected_body_contains"]:
        assert text in body

    facts = {
        fact["key"]: fact["value"]
        for fact in response_data["confirmed_facts"]
        if fact["status"] != "conflicted"
    }
    for key, value in case["expected_facts"].items():
        assert facts[key] == value

    assert set(case["expected_intents"]).issubset(response_data["reply_draft"]["answer_intents"])
    if case["requires_grounding"]:
        assert response_data["reply_draft"]["generation_method"] == ("rag_grounded_template")
        assert response_data["reply_draft"]["source_ids"]
        retrieval_ids = {source["chunk_id"] for source in response_data["retrieval"]["sources"]}
        assert set(response_data["reply_draft"]["source_ids"]).issubset(retrieval_ids)
