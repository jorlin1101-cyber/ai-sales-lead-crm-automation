"""Exercise the customer-visible draft from the same API as a live conversation."""

from pathlib import Path
from datetime import date
import re

import pytest

from lead_cleaner.answerability_evaluation.adapters import run_observations
from lead_cleaner.answerability_evaluation.dataset import load_dataset
from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.services.sales_handoff import assess_sales_review, requested_checks
from lead_cleaner.services.conversation_slots import fact


@pytest.fixture(scope="module", params=["rule_only", "mocked_model"])
def turns(request, tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    data = load_dataset(root, "p0-02.v2")
    ids = {"AB03", "AB10", "AB11", "AB15", "AB16", "AB17", "AB18", "AB20", "AB21", "AB24"}
    data["cases"] = [case for case in data["cases"] if case["case_id"] in ids]
    rows = run_observations(root, data, request.param, tmp_path_factory.mktemp(request.param))
    assert all(row["api_status"] == 200 for row in rows)
    return {(row["case_id"], row["turn_id"]): row["response"] for row in rows}


def test_expired_and_undated_promotions_are_distinct(turns):
    mixed = turns["AB10", "T1"]["reply_draft"]
    assert "昆明" in mixed["body_text"] and "已截止" in mixed["body_text"]
    assert "销售" in mixed["body_text"] and len(mixed["source_ids"]) == 2
    expired = turns["AB16", "T1"]["reply_draft"]["body_text"].lower()
    assert "ended" in expired and "sales" in expired
    undated = turns["AB17", "T1"]["reply_draft"]["body_text"].lower()
    assert "no verifiable validity" in undated and "ended" not in undated and "sales" in undated


def test_deposit_and_payment_methods_do_not_imply_a_customer_order(turns):
    reply = turns["AB03", "T1"]["reply_draft"]["body_text"].lower()
    assert "30%" in reply and "paypal" in reply
    assert "order record" not in reply and "booking completion" not in reply


def test_both_conflicting_deadlines_are_cited_and_deposit_is_answered(turns):
    draft = turns["AB11", "T1"]["reply_draft"]
    assert "30%" in draft["body_text"] and "销售" in draft["body_text"]
    assert re.search(r"抵达|arrival", draft["body_text"], re.I)
    assert re.search(r"出发|departure", draft["body_text"], re.I)
    assert len(draft["source_ids"]) >= 2 and draft["status"] == "needs_human_review"


def test_conflicting_refunds_preserve_the_two_source_quotes(turns):
    draft = turns["AB15", "T1"]["reply_draft"]
    assert re.search("full refund", draft["body_text"], re.I)
    assert re.search("non-refundable", draft["body_text"], re.I)
    assert len(draft["source_ids"]) == 2
    assert draft["status"] == "needs_human_review"


def test_booking_and_availability_are_distinct_and_do_not_reask_known_dates(turns):
    result = turns["AB18", "T1"]
    draft = result["reply_draft"]
    assert re.search(r"supplier.{0,30}(inventory|availability)", draft["body_text"], re.I)
    assert re.search(r"order record", draft["body_text"], re.I)
    assert not any(re.search(r"date|when", q, re.I) for q in result["open_questions"])
    assert "order record" in turns["AB21", "T2"]["reply_draft"]["body_text"].lower()
    assert "order record" not in turns["AB21", "T3"]["reply_draft"]["body_text"].lower()
    assert "inventory" not in turns["AB20", "T3"]["reply_draft"]["body_text"].lower()
    follow_up = turns["AB24", "T3"]["reply_draft"]["body_text"].lower()
    assert re.search(r"child room price|儿童房价", follow_up)
    assert re.search(r"inventory|库存", follow_up)


def _source(text, key="one", product=None):
    return RetrievedChunk(
        chunk_id=key,
        source_type="notion_page",
        notion_page_id=key,
        source_path="guide",
        source_title="Booking guide",
        doc_type="faq",
        region="general",
        product_name=product,
        section="Conditions",
        text=text,
        rank=1,
        score=1.0,
        retrieval_source="bm25",
    )


@pytest.mark.parametrize(
    ("reference", "status"),
    [
        (date(2030, 1, 1), "starts on"),
        (date(2030, 2, 28), "falls within"),
        (date(2030, 3, 1), "ended on"),
    ],
)
def test_offer_dates_are_based_on_the_stated_window_and_injected_clock(reference, status):
    message = "Can we still use the CNY 105 special offer?"
    source = _source("The promotion was CNY 105 per guest in February 2030 only.")
    review = assess_sales_review(
        requested_checks(message), message, [source], [], None, "en", reference
    )
    assert status in review.notes[0] and "Sales must verify" in review.notes[0]
    assert review.sources == [source]


@pytest.mark.parametrize(
    "source",
    [
        "The special offer quotes CNY 77 for May 2025 without effective dates.",
        "Guide updated May 2025. The special offer is CNY 77.",
        "The special offer is CNY 77, 2030-04-20 to 2030-04-01.",
        "The special offer is CNY 77, 2030-15-20 to 2030-18-01.",
    ],
)
def test_publication_dates_and_invalid_ranges_cannot_establish_offer_validity(source):
    message = "CNY 77 特价是否还有效？"
    review = assess_sales_review(
        requested_checks(message), message, [_source(source)], [], None, "zh", date(2030, 4, 1)
    )
    assert "无法判断" in review.notes[0] and "已截止" not in review.notes[0]


def test_different_products_or_deadlines_are_not_a_refund_conflict():
    message = "Is my deposit refundable 10 days before departure?"
    sources = [
        _source("Cancellation 10 days before departure gets a full refund.", "one", "family"),
        _source("Cancellation 10 days before departure is non-refundable.", "two", "ski"),
        _source("Cancellation 9 days before departure is non-refundable.", "three", "family"),
    ]
    review = assess_sales_review(
        requested_checks(message), message, sources, [], None, "en", date(2030, 1, 1)
    )
    assert not review.notes


def test_date_already_supplied_in_history_and_new_topic_switch():
    facts = [fact("travel_date", "2032-05-03", "original-message")]
    message = "这天还有空房吗？能否确认预订成功？"
    review = assess_sales_review(
        requested_checks(message), message, [], facts, None, "zh", date(2032, 4, 1)
    )
    assert review.questions == []
    assert "库存" in " ".join(review.notes) and "订单" in " ".join(review.notes)
    assert not requested_checks("Leave hotel availability for later. What is the itinerary?")


@pytest.mark.parametrize(
    "message",
    [
        "What deposit percentage confirms a private-tour booking, and which payment methods are accepted?",
        "Which documents do we need to confirm a reservation?",
        "How much do I pay to confirm my booking?",
        "请问需要交多少定金才能确认预订？",
    ],
)
def test_general_booking_requirements_do_not_open_an_order_check(message):
    assert "booking" not in requested_checks(message)


@pytest.mark.parametrize(
    "message",
    [
        "I paid a deposit. Is my reservation confirmed now?",
        "Which deposit confirms a booking, and has our hotel room already been booked?",
        "确认预订要交多少定金？我的订单已经确认了吗？",
        "No supplier has confirmed a booking. Is it really confirmed?",
    ],
)
def test_explicit_order_status_request_still_requires_evidence(message):
    assert "booking" in requested_checks(message)
