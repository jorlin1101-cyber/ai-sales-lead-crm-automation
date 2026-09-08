from lead_cleaner.config import RagBackend
from lead_cleaner.services.conversation_slots import equivalent_budget, valid_date
from tests.test_conversations import make_client, message_payload


def send(client, mid, text):
    response = client.post(
        "/conversations/messages", json=message_payload(mid, text, channel="web_chat")
    )
    assert response.status_code == 200, response.text
    return response.json()


def facts(result):
    return {item["key"]: item for item in result["confirmed_facts"]}


def test_service_cancellation_is_not_global_opt_out(tmp_path):
    with make_client(tmp_path) as client:
        send(client, "one", "10个人去川西，10月1日出发，酒店4星，需要导游和包车，请报价")
        result = send(client, "two", "不再需要导游，但我们仍然要包车去川西")
    assert result["state"] != "do_not_contact"
    assert facts(result)["guide_language"]["value"] == "不需要导游"


def test_negated_preferences_are_not_accepted_as_positive(tmp_path):
    with make_client(tmp_path) as client:
        result = send(client, "one", "导游不要英语，用车不要大巴，酒店不是五星是四星")
    current = facts(result)
    assert current["guide_language"]["status"] == "pending"
    assert current["vehicle"]["status"] == "pending"
    assert current["hotel_tier"]["value"] == "4星级"


def test_destination_replacement_scopes_rag_sources(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        send(client, "one", "请介绍川西产品")
        result = send(client, "two", "我们不去川西了，改去云南，请介绍云南行程")
    assert facts(result)["destination"]["value"] == "Yunnan"
    assert all(
        "Western Sichuan" not in source["source_title"] for source in result["retrieval"]["sources"]
    )


def test_short_answer_uses_pending_question_context(tmp_path):
    with make_client(tmp_path) as client:
        send(client, "one", "10个人去川西，10月1日出发，酒店四星，请报价")
        result = send(client, "two", "中文")
    assert facts(result)["guide_language"]["value"] == "中文"


def test_retraction_marks_slots_pending(tmp_path):
    with make_client(tmp_path) as client:
        send(client, "one", "酒店四星，导游语言中文")
        result = send(client, "two", "酒店还没确定，导游语言也待定")
    assert facts(result)["hotel_tier"]["status"] == "pending"
    assert facts(result)["guide_language"]["status"] == "pending"


def test_budget_normalization_date_validation_and_added_slots(tmp_path):
    assert equivalent_budget("预算人均5000元", "人均5000元")
    assert valid_date("10月3日到7日") and not valid_date("13月40日")
    with make_client(tmp_path) as client:
        send(client, "one", "预算人均5000元")
        same = send(client, "two", "人均5000元")
        detailed = send(client, "three", "13月40日出发，一共7天，有老人需要无障碍客房")
    assert facts(same)["budget"]["status"] != "conflicted"
    current = facts(detailed)
    assert current["travel_date"]["status"] == "pending"
    assert current["duration_days"]["value"] == "7"
    assert "无障碍客房" in current["special_requirements"]["value"]


def test_one_canonical_missing_list_drives_state_and_draft(tmp_path):
    with make_client(tmp_path) as client:
        result = send(client, "one", "10个人去川西，10月1日出发，酒店四星，请报价")
    assert result["open_questions"] == []
    assert result["state"] in {"ready_for_review", "needs_human_review"}
    assert "请再确认：" not in result["reply_draft"]["body_text"]
