from pathlib import Path
from unittest.mock import Mock
import json

import pytest

from lead_cleaner.config import RagBackend, Settings
from lead_cleaner.rag.retriever_factory import create_rag_retriever
from lead_cleaner.services.conversation_llm import QwenConversationLLM
from lead_cleaner.services.conversation_slots import fact
from lead_cleaner.services.product_recommendation import recommend_product
from tests.test_conversations import make_client, message_payload
from tests.test_conversation_llm import response


def send(client, number, message, channel="web_chat"):
    result = client.post(
        "/conversations/messages", json=message_payload(str(number), message, channel=channel)
    )
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize(
    "destination,name,days,route",
    [
        ("川西", "Western Sichuan Private Tour", "8", "成都—康定"),
        ("云南", "Yunnan Family Tour", "7", "昆明—大理"),
        ("西藏", "Tibet Cultural Tour", "5", "拉萨"),
    ],
)
def test_demand_only_turn_recommends_a_real_product_without_waiting_for_all_slots(
    tmp_path, destination, name, days, route
):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        data = send(client, 1, f"我们4个人想去{destination}，一共{days}天。")
        draft = data["reply_draft"]
        product = draft["recommended_products"][0]
        assert product["product_name"] == name
        assert product["fit_status"] == "candidate"
        assert product["display_name"] in draft["body_text"]
        assert route in draft["body_text"]
        assert not data["open_questions"]
        assert set(product["source_ids"]).issubset(draft["source_ids"])
        assert set(draft["source_ids"]).issubset(
            s["chunk_id"] for s in data["retrieval"]["sources"]
        )
        restored = client.get(f"/conversations/{data['conversation_id']}/latest").json()
        assert restored["reply_draft"]["recommended_products"] == draft["recommended_products"]


def test_service_details_continue_product_proposal_and_destination_change_replaces_it(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        send(client, 1, "我们8个人去川西，10月3日出发，想玩7天，请报价")
        second = send(client, 2, "酒店四星，需要包车，中文导游")
        assert (
            second["reply_draft"]["recommended_products"][0]["product_name"]
            == "Western Sichuan Private Tour"
        )
        assert (
            second["reply_draft"]["recommended_products"][0]["fit_status"] == "needs_customization"
        )
        assert "酒店等级" not in second["open_questions"]
        third = send(client, 3, "改去云南")
        assert (
            third["reply_draft"]["recommended_products"][0]["product_name"] == "Yunnan Family Tour"
        )
        assert "川西私人定制游" not in third["reply_draft"]["body_text"]
        fourth = send(client, 4, "改去北京，请推荐产品")
        assert not fourth["reply_draft"]["recommended_products"]
        assert "尚未检索到" in fourth["reply_draft"]["body_text"]


def test_product_mismatch_is_disclosed_and_budget_is_not_a_price(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        result = send(client, 1, "我们20个人去云南，只有3天，预算人均5000元，请报价")
    draft = result["reply_draft"]
    product = draft["recommended_products"][0]
    assert product["fit_status"] == "needs_customization"
    assert len(product["adjustments"]) == 2
    assert "7天6晚" in draft["body_text"]
    assert "不等于产品售价" in draft["body_text"]
    assert "5000元" not in " ".join(product["manual_summary"])
    assert any(
        s["source_title"] == "Private Tour Pricing Rules" for s in result["retrieval"]["sources"]
    )


def test_product_inquiry_asks_only_selection_questions(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        data = send(client, 1, "想去云南，有什么产品？")
    assert data["reply_draft"]["recommended_products"]
    assert data["open_questions"] == ["行程天数", "同行人数"]
    assert "预算范围" not in data["reply_draft"]["body_text"]


def test_disabled_or_unknown_product_does_not_invent_a_recommendation(tmp_path):
    with make_client(tmp_path) as client:
        data = send(client, 1, "请推荐云南产品")
    assert data["reply_draft"]["recommended_products"] == []
    assert data["reply_draft"]["source_ids"] == []
    assert "尚未检索到" in data["reply_draft"]["body_text"]
    assert data["requires_human_review"]


def test_ack_optout_and_permit_only_do_not_trigger_product_sales(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        send(client, 1, "请推荐西藏产品")
        for n, message in enumerate(
            ["好的，谢谢", "西藏入藏证件和付款规则是什么？", "请退订，不要再联系我"], 2
        ):
            data = send(client, n, message)
            assert data["reply_draft"]["recommended_products"] == []
        assert data["state"] == "do_not_contact"
        assert not data["reply_draft"]["body_text"]


def test_email_proposal_has_channel_format_in_english(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        data = send(
            client,
            1,
            "We are 4 people visiting Yunnan for 7 days. Please recommend a product.",
            "email",
        )
    draft = data["reply_draft"]
    assert draft["subject"].startswith("Re:")
    assert draft["body_text"].startswith("Hello,")
    assert draft["body_text"].endswith("Sales Team")
    assert "Yunnan Family Tour" in draft["body_text"]
    assert "7 days / 6 nights" in draft["body_text"]
    assert not data["open_questions"]


def test_model_is_called_after_detail_turn_and_cannot_drop_server_product_and_constraints(tmp_path):
    mock_client = Mock()

    def completion(**kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        if "recommended_products" not in payload:
            return response('{"updates":[]}')
        product = payload["recommended_products"][0]
        assert product["product_name"] == "Western Sichuan Private Tour"
        evidence = next(e for e in payload["evidence"] if "days" in e["quote"])
        return response(
            json.dumps(
                {
                    "paragraphs": [
                        {"evidence_id": evidence["evidence_id"], "text": "具体线路可依照手册安排。"}
                    ]
                }
            )
        )

    mock_client.chat.completions.create.side_effect = completion
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        client.app.state.conversation_llm = QwenConversationLLM(mock_client, "qwen-test")
        send(client, 1, "我们8个人想去川西，一共7天")
        data = send(client, 2, "酒店四星，需要包车，中文导游")
    assert data["llm_trace"]["generation"] == "succeeded"
    assert mock_client.chat.completions.create.call_count == 4
    draft = data["reply_draft"]
    assert "川西私人定制游" in draft["body_text"]
    assert "8天7晚" in draft["body_text"]
    assert "标准方案" in draft["body_text"]
    assert not data["open_questions"]
    assert set(draft["recommended_products"][0]["source_ids"]).issubset(draft["source_ids"])


def test_manual_missing_sections_or_changed_revision_cannot_fabricate_product_details():
    settings = Settings(
        _env_file=None,
        rag_backend=RagBackend.KEYWORD_RRF,
        knowledge_chunks_path=Path("data/knowledge_snapshot/knowledge_chunks.json"),
    )
    retriever = create_rag_retriever(settings)
    manuals = retriever.product_manuals("yunnan")
    facts = [fact("destination", "Yunnan", "1")]
    assert recommend_product([], facts, "zh") == (None, [])
    assert recommend_product(manuals[:1], facts, "zh") == (None, [])
    assert recommend_product(manuals, [fact("destination", "Yunnan", "1", pending=True)], "zh") == (
        None,
        [],
    )
    changed = [
        c.model_copy(
            update={"text": "# Product\n## Typical Duration\n- Classic trip: 9 days / 8 nights."}
        )
        if c.section == "Typical Duration"
        else c
        for c in manuals
    ]
    product, _ = recommend_product(changed, facts, "zh")
    assert product is not None
    assert "9 days" in " ".join(product.manual_summary)
    assert "7天6晚" not in " ".join(product.manual_summary)
