import sqlite3

import pytest

from tests.test_conversation_business_logic import facts, send
from tests.test_conversations import make_client


@pytest.mark.parametrize(
    ("corrected", "count"),
    [
        ("更正一下，不是8个人，是9个人。Does this change the known pricing principles?", "9"),
        ("We are not 8 people, we are 11 people.", "11"),
        ("There are 12 people, not 8 people.", "12"),
    ],
)
def test_group_correction_survives_restart_and_keeps_source(tmp_path, corrected, count):
    with make_client(tmp_path) as client:
        first = send(client, "initial", "我们8个人计划去云南，请介绍价格。")
        assert facts(first)["group_size"]["value"] == "8"
        second = send(client, "correction", corrected)
        second_fact = facts(second)["group_size"]
        assert second_fact["value"] == count
        assert second_fact["status"] == "customer_confirmed"
        timeline = client.get(f"/conversations/{first['conversation_id']}/timeline").json()
        correction_id = next(turn["message_id"] for turn in timeline if turn["turn_number"] == 2)
        assert second_fact["source_message_id"] == correction_id
        assert count in second["reply_draft"]["body_text"]
    with make_client(tmp_path) as reopened:
        third = send(reopened, "follow-up", "还有哪些定价因素？")
        assert facts(third)["group_size"] == second_fact
        assert count in third["reply_draft"]["body_text"]
    with sqlite3.connect(tmp_path / "conversations.sqlite3") as db:
        stored = db.execute(
            "SELECT fact_value, source_message_id FROM conversation_facts "
            "WHERE conversation_id = ? AND fact_key = 'group_size'",
            (first["conversation_id"],),
        ).fetchone()
    assert stored == (count, correction_id)


@pytest.mark.parametrize(
    ("text", "excluded"),
    [
        (
            "云南私人团的定金比例是多少？余款的14天期限究竟按抵达日期还是出发日期计算？",
            "duration_days",
        ),
        ("Is the balance due 14 days before departure?", "duration_days"),
        ("套餐是否包含英语导游？", "guide_language"),
        (
            "For a private Yunnan family tour, is an English-speaking guide included and what exact daily hours are covered?",
            "guide_language",
        ),
        ("我们不是8个人。", "group_size"),
        ("Does the discount start at 8 people?", "group_size"),
    ],
)
def test_policy_questions_and_rejected_counts_do_not_create_facts(tmp_path, text, excluded):
    with make_client(tmp_path) as client:
        assert excluded not in facts(send(client, "question", text))


def test_policy_questions_preserve_distinct_customer_assertions(tmp_path):
    with make_client(tmp_path) as client:
        initial = send(client, "initial", "我们需要中文导游，计划玩7天。")
        followup = send(
            client,
            "followup",
            "Is an English-speaking guide included? Is payment due 14 days before departure?",
        )
        for key, value in [("guide_language", "中文"), ("duration_days", "7")]:
            assert facts(initial)[key]["value"] == value
            assert facts(followup)[key] == facts(initial)[key]
        mixed = send(
            client,
            "mixed",
            "Is the balance due 14 days before departure? We now plan a 7-day trip.",
        )
        assert facts(mixed)["duration_days"]["value"] == "7"
