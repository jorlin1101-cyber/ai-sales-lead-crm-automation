import sqlite3
from unittest.mock import Mock

import pytest

from lead_cleaner.services.conversation_llm import SlotUpdate, Understanding
from tests.test_conversation_business_logic import facts, send
from tests.test_conversations import make_client


@pytest.mark.parametrize(
    ("corrected", "count"),
    [
        ("更正一下，不是8个人，是9个人。Does this change the known pricing principles?", "9"),
        ("We are not 8 people, we are 11 people.", "11"),
        ("There are 12 people, not 8 people.", "12"),
        ("这次人数从8人改为10人。请沿用原来的行程。", "10"),
        ("We changed our group size from 8 people to 13 people.", "13"),
        ("Actually, there are 14 of us, not 8.", "14"),
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


def test_withdrawal_of_previous_count_is_pending_without_a_replacement(tmp_path):
    with make_client(tmp_path) as client:
        initial = send(client, "initial", "Our group of 8 plans to visit Yunnan.")
        hypothetical = send(
            client, "hypothetical", "If there are 15 people, what discount is available?"
        )
        assert facts(hypothetical)["group_size"] == facts(initial)["group_size"]
        rejected = send(client, "withdraw", "We are not 8 people. I will confirm the final count.")
        pending = facts(rejected)["group_size"]
        assert pending["status"] == "pending"
        assert pending["source_message_id"] != facts(initial)["group_size"]["source_message_id"]
        assert rejected["current_analysis"]["analysis_result"]["features"]["group_size"] is None


def test_declared_preferences_can_share_a_turn_with_policy_questions(tmp_path):
    with make_client(tmp_path) as client:
        mixed = send(
            client,
            "mixed",
            "Is an English guide included? We prefer a French guide and we plan a 7-day trip. Is payment due 14 days before departure?",
        )
        assert facts(mixed)["guide_language"]["value"] == "French"
        assert facts(mixed)["duration_days"]["value"] == "7"
        question = send(
            client,
            "question",
            "I would like to know whether an English guide is included. Do you offer 5-day trips?",
        )
        assert facts(question)["guide_language"] == facts(mixed)["guide_language"]
        assert facts(question)["duration_days"] == facts(mixed)["duration_days"]


def test_model_proposals_must_use_customer_facts_even_with_verbatim_policy_evidence(tmp_path):
    model = Mock(model="simulated-understanding")
    model.understand.return_value = Understanding(
        updates=[
            SlotUpdate(key="group_size", operation="replace", value="8", evidence="不是8个人"),
            SlotUpdate(key="guide_language", operation="set", value="英语", evidence="英语导游"),
            SlotUpdate(key="duration_days", operation="set", value="14", evidence="14天"),
        ]
    )
    with make_client(tmp_path) as client:
        client.app.state.conversation_llm = model
        result = send(
            client, "combined", "不是8个人，是9个人。套餐包含英语导游吗？余款提前14天付吗？"
        )
        assert result["llm_trace"]["understanding"] == "succeeded"
        recorded = facts(result)
        assert recorded["group_size"]["value"] == "9"
        assert "guide_language" not in recorded
        assert "duration_days" not in recorded
