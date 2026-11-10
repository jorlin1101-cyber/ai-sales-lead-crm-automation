"""Business questions should be answered from the matching statements, in either generation path."""

from pathlib import Path

import pytest

from lead_cleaner.answerability_evaluation import adapters
from lead_cleaner.answerability_evaluation.dataset import load_dataset

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode", adapters.MODES)
def test_specific_inquiries_select_claims_and_use_confirmed_dates(mode, tmp_path):
    dataset = load_dataset(ROOT, "p0-02.v2")
    dataset["cases"] = [
        c
        for c in dataset["cases"]
        if c["case_id"] in {"AB01", "AB03", "AB07", "AB09", "AB19", "AB20", "AB22", "AB23"}
    ]
    messages = {
        "AB03": ["订金要付几成，what payment methods do you accept?"],
        "AB07": [
            "What determines the price of a private Yunnan tour? Which child discounts apply, and how much does the child room cost?"
        ],
        "AB23": [
            "我们计划于2026年11月2日出发。云南亲子团含机场接送吗？",
            "Is my departure date eligible for the complimentary craft workshop?",
            "免费手工活动的有效日期是什么？",
        ],
    }
    for case in dataset["cases"]:
        for turn, text in zip(case["turns"], messages.get(case["case_id"], [])):
            turn["message"] = text
    observations = adapters.run_observations(ROOT, dataset, mode, tmp_path)
    assert all(
        o["api_status"] == 200 and o["execution_status"] == "completed" for o in observations
    )
    draft = {(o["case_id"], o["turn_id"]): o["response"]["reply_draft"] for o in observations}

    missing = draft["AB01", "T1"]
    assert missing["source_ids"] == [] and "核实" in missing["body_text"]
    pay = draft["AB03", "T1"]
    assert all(word in pay["body_text"] for word in ["30%", "4%", "PayPal", "Stripe"])
    assert "14" not in pay["body_text"] and not pay["open_questions"]
    price = draft["AB07", "T1"]
    assert all(
        w in price["body_text"].lower()
        for w in [
            "group size",
            "hotel level",
            "vehicle type",
            "guide service",
            "season",
            "under 12",
            "sharing room with parents",
            "verify",
        ]
    )
    assert len(price["source_ids"]) == 2 and not price["open_questions"]
    if mode == "mocked_model":
        assert pay["generation_method"] == price["generation_method"] == "llm_grounded"
    exclusions = draft["AB20", "T3"]
    assert all(
        item in exclusions["body_text"].lower()
        for item in ["flights", "visa fees", "tips", "personal expenses", "travel insurance"]
    )
    assert exclusions["source_ids"] == ["chunk_88e6a3c65309"] and not exclusions["open_questions"]
    zh_exclusions = draft["AB22", "T3"]
    assert all(
        item in zh_exclusions["body_text"]
        for item in ["机票", "签证费", "小费", "个人消费", "旅行保险"]
    )
    conditional = draft["AB09", "T1"]
    assert (
        "Kunming Airport" in conditional["body_text"]
        and "other cities" in conditional["body_text"].lower()
    )
    assert conditional["open_questions"] == ["What is your departure date?"]
    assert "您的" not in conditional["body_text"] and "云南" not in conditional["body_text"]
    assert draft["AB23", "T1"]["source_ids"] == ["transfer"]
    checked = draft["AB23", "T2"]
    assert checked["source_ids"] == ["date_policy"] and checked["open_questions"] == []
    assert "2026-11-02" in checked["body_text"] and "outside" in checked["body_text"].lower()
    assert "2026年10月1日至31日" in draft["AB23", "T3"]["body_text"]
    assert "年龄" in draft["AB19", "T1"]["open_questions"][0]
    assert (
        "符合手册" in draft["AB19", "T2"]["body_text"] and not draft["AB19", "T2"]["open_questions"]
    )


def test_explicit_group_size_reference_uses_the_current_fact():
    from lead_cleaner.services.conversation_slots import fact
    from lead_cleaner.services.inquiry_evidence import inquiry_topics, point_guidance

    message = "按照刚才更正的人数，which items are excluded from the private-tour quotation?"
    notes, _ = point_guidance(
        inquiry_topics(message), [], [fact("group_size", "11", "current")], "zh", message
    )
    assert "11 人" in " ".join(notes)
