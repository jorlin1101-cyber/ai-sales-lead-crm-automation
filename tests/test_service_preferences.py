from unittest.mock import patch

import pytest

from lead_cleaner.config import RagBackend
from lead_cleaner.services.service_preferences import extract_preferences, FLEXIBLE
from tests.test_conversations import make_client, message_payload


@pytest.mark.parametrize(
    "message,expected",
    [
        (
            "酒店等级4星级，需要车，导游语言汉语",
            {
                "hotel_tier": "4星级",
                "vehicle": "需要用车（车型由顾问安排）",
                "guide_language": "中文",
            },
        ),
        (
            "酒店等级都可以，需要车，导游语言汉语",
            {
                "hotel_tier": FLEXIBLE,
                "vehicle": "需要用车（车型由顾问安排）",
                "guide_language": "中文",
            },
        ),
        (
            "酒店：四星，车型：7座商务车，导游语言：英语",
            {"hotel_tier": "4星级", "vehicle": "7座商务车", "guide_language": "英语"},
        ),
        (
            "hotel tier: 4-star, vehicle: private car, guide language: English",
            {"hotel_tier": "4星级", "vehicle": "private car", "guide_language": "英语"},
        ),
        (
            "无需安排酒店，不需要车，不用导游",
            {"hotel_tier": "无需安排住宿", "vehicle": "不需要用车", "guide_language": "不需要导游"},
        ),
        ("酒店未定，用车还没想好，导游语言不确定", {}),
        ("酒店等级，用车需求，导游语言", {}),
        (
            "四星级，包车，中文导游",
            {"hotel_tier": "4星级", "vehicle": "包车", "guide_language": "中文"},
        ),
    ],
)
def test_labelled_and_natural_preferences(message, expected):
    assert {f.key: f.value for f in extract_preferences(message, "msg")} == expected


def turn(client, number, message):
    response = client.post("/conversations/messages", json=message_payload(str(number), message))
    assert response.status_code == 200, response.text
    return response.json()


def test_exact_customer_three_turns_stop_repeating_known_preferences(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        turn(client, 1, "我们有10个人，准备去川西，10月国庆出发，预算人均5000，有推荐吗")
        second = turn(client, 2, "出发日期10月1日，一共去7天，酒店等级4星级")
        assert "酒店等级" not in second["open_questions"]
        third = turn(client, 3, "酒店等级都可以，需要车，导游语言汉语")
        known = {f["key"]: f for f in third["confirmed_facts"]}
        for key in ("hotel_tier", "vehicle", "guide_language"):
            assert known[key]["status"] == "customer_confirmed"
        assert known["hotel_tier"]["value"] == FLEXIBLE
        assert "请再确认：" not in third["reply_draft"]["body_text"]
        fourth = turn(client, 4, "请继续提供报价规则")
        assert "请再确认：" not in fourth["reply_draft"]["body_text"]


def test_old_conversation_recovers_missed_preferences_without_user_retyping(tmp_path):
    with make_client(tmp_path, rag_backend=RagBackend.KEYWORD_RRF) as client:
        with patch(
            "lead_cleaner.services.conversation_service.extract_preferences", return_value=[]
        ):
            turn(client, 1, "我们10人去川西，10月1日出发，请报价")
            turn(client, 2, "酒店等级4星级，需要车，导游语言汉语")
        current = turn(client, 3, "请继续提供报价规则")
        known = {f["key"]: f for f in current["confirmed_facts"]}
        assert known["hotel_tier"]["value"] == "4星级"
        assert known["guide_language"]["value"] == "中文"
        assert "请再确认：" not in current["reply_draft"]["body_text"]
        timeline = client.get(f"/conversations/{current['conversation_id']}/timeline").json()
        assert known["hotel_tier"]["source_message_id"] == timeline[1]["message_id"]


def test_rephrasing_same_preferences_does_not_create_conflict(tmp_path):
    with make_client(tmp_path) as client:
        turn(client, 1, "酒店四星，中文导游")
        current = turn(client, 2, "酒店4星级，导游语言普通话")
        assert not any(f["status"] == "conflicted" for f in current["confirmed_facts"])
