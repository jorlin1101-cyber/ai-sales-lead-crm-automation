from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from lead_cleaner.config import Settings
from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.conversation import ConversationMessageRequest, ReplyDraft
from lead_cleaner.services.conversation_llm import (
    ConversationLLMError,
    QwenConversationLLM,
    SlotUpdate,
    Understanding,
    apply_understanding,
)
from lead_cleaner.services.conversation_slots import fact
from tests.test_conversations import make_client, message_payload


def response(content, finish="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish, message=SimpleNamespace(content=content, refusal=None)
            )
        ]
    )


def qwen_with(content):
    client = Mock()
    client.chat.completions.create.return_value = response(content)
    return QwenConversationLLM(client, "qwen-test"), client


def request():
    return ConversationMessageRequest(
        **message_payload("one", "请介绍川西报价", channel="web_chat")
    )


def draft():
    return ReplyDraft(
        draft_id="d1",
        channel="web_chat",
        conversation_id="c1",
        turn_number=1,
        status="ready_for_review",
        body_text="old",
        display_text="old",
        open_questions=["酒店等级"],
        policy_version="policy-v1",
    )


def chunk():
    return RetrievedChunk(
        chunk_id="chunk-1",
        source_type="notion_page",
        notion_page_id="n1",
        source_title="Pricing",
        source_path="/pricing",
        doc_type="pricing",
        region="general",
        section="Pricing Notes",
        text="人数和酒店等级会影响报价。",
        score=1,
        rank=1,
        retrieval_source="fusion",
    )


def test_qwen_understanding_uses_json_mode_and_normalizes():
    qwen, client = qwen_with(
        '{"updates":[{"key":"guide_language","value":"普通话","operation":"set","evidence":"中文"}]}'
    )
    result = qwen.understand("中文", [], ["导游语言"], [])
    assert result.updates[0].value == "中文"
    call = client.chat.completions.create.call_args.kwargs
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == {"enable_thinking": False}
    assert "Return JSON only" in call["messages"][0]["content"]


@pytest.mark.parametrize(
    "content,code",
    [
        (
            '{"updates":[{"key":"group_size","value":"8","operation":"set","evidence":"不存在"}]}',
            "unsupported_fact_evidence",
        ),
        (
            '{"updates":[{"key":"travel_date","value":"13月40日","operation":"set","evidence":"13月40日"}]}',
            "invalid_slot_value",
        ),
        (
            '{"updates":[{"key":"group_size","value":"8","operation":"set","evidence":"8人"},{"key":"group_size","value":"9","operation":"set","evidence":"9人"}]}',
            "duplicate_slot_update",
        ),
    ],
)
def test_qwen_understanding_rejects_unsupported_updates(content, code):
    qwen, _ = qwen_with(content)
    with pytest.raises(ConversationLLMError, match=code):
        qwen.understand("8人、9人、13月40日", [], [], [])


def test_qwen_compose_requires_source_quote_and_uses_server_questions():
    qwen, _ = qwen_with('{"paragraphs":[{"evidence_id":"e1s1","text":"报价会受到酒店等级影响。"}]}')
    result = qwen.compose(request(), draft(), [], [chunk()], "zh")
    assert result.generation_method == "llm_grounded"
    assert result.source_ids == ["chunk-1"]
    assert "酒店等级" in result.body_text
    assert result.evidence[0]["sha256"]
    assert result.evidence[0]["supporting_quote"] == "人数和酒店等级会影响报价。"


@pytest.mark.parametrize(
    "payload,code",
    [
        (
            '{"paragraphs":[{"evidence_id":"missing","text":"报价取决于需求。"}]}',
            "unsupported_answer_evidence",
        ),
        (
            '{"paragraphs":[{"evidence_id":"e1s1","text":"请确认酒店等级？"}]}',
            "unplanned_followup",
        ),
        (
            '{"paragraphs":[{"evidence_id":"e1s1","text":"报价是5000元。"}]}',
            "unsupported_numeric_claim",
        ),
    ],
)
def test_qwen_compose_rejects_ungrounded_content(payload, code):
    qwen, _ = qwen_with(payload)
    with pytest.raises(ConversationLLMError, match=code):
        qwen.compose(request(), draft(), [], [chunk()], "zh")


def test_apply_understanding_handles_replacement_pending_and_human_conflict():
    previous = [fact("destination", "Western Sichuan", "m1"), fact("hotel_tier", "4星级", "m1")]
    previous[1] = previous[1].model_copy(update={"status": "human_confirmed"})
    result = Understanding(
        updates=[
            SlotUpdate(key="destination", value="Yunnan", operation="replace", evidence="云南"),
            SlotUpdate(key="hotel_tier", value="5星级", operation="replace", evidence="五星"),
            SlotUpdate(key="vehicle", value="待定", operation="pending", evidence="待定"),
        ]
    )
    old, incoming = apply_understanding(previous, [], result, "m2")
    assert not any(item.key == "destination" for item in old)
    current = {item.key: item for item in incoming}
    assert current["destination"].value == "Yunnan"
    assert current["hotel_tier"].status == "conflicted"
    assert current["vehicle"].status == "pending"


def test_qwen_factory_is_explicit_and_closeable():
    assert QwenConversationLLM.from_settings(Settings(_env_file=None)) is None
    configured = Settings(
        _env_file=None,
        allow_network=True,
        conversation_llm_enabled=True,
        dashscope_api_key=SecretStr("secret"),
    )
    qwen = QwenConversationLLM.from_settings(configured)
    assert qwen is not None and qwen.model == "qwen3.7-plus"
    qwen.close()


def test_conversation_service_records_real_stage_usage_without_extra_feature_call(tmp_path):
    class Dummy:
        model = "qwen-test"

        def understand(self, *args):
            return Understanding(updates=[])

        def compose(self, request, draft, facts, chunks, language):
            return draft.model_copy(update={"generation_method": "llm_grounded"})

    with make_client(tmp_path, rag_backend="keyword_rrf") as client:
        client.app.state.conversation_llm = Dummy()
        result = client.post(
            "/conversations/messages",
            json=message_payload("one", "请介绍川西报价", channel="web_chat"),
        ).json()
    assert result["llm_trace"] == {
        "provider": "dashscope",
        "model": "qwen-test",
        "understanding": "succeeded",
        "generation": "succeeded",
    }
    assert result["reply_draft"]["generation_method"] == "llm_grounded"


def test_conversation_service_records_model_fallback_for_review(tmp_path):
    class Unavailable:
        model = "qwen-test"

        def understand(self, *args):
            raise ConversationLLMError("provider_error")

    with make_client(tmp_path, rag_backend="keyword_rrf") as client:
        client.app.state.conversation_llm = Unavailable()
        result = client.post(
            "/conversations/messages",
            json=message_payload("fallback", "请介绍川西报价", channel="web_chat"),
        ).json()
    assert result["llm_trace"]["understanding"] == "fallback:provider_error"
    assert result["requires_human_review"] is True
    assert "Model fallback" in result["reply_draft"]["internal_note"]
