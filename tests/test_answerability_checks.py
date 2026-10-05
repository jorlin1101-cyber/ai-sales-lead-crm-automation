from copy import deepcopy
import hashlib

import pytest

from lead_cleaner.answerability_evaluation.checks import (
    adjudicate_claims,
    evaluate_assertions,
    expected_keys,
    expected_retrieval_keys,
    score_observation,
)
from lead_cleaner.answerability_evaluation.metrics import summarize_replies
from lead_cleaner.answerability_evaluation.reports import content_hash


@pytest.fixture
def example():
    text = "Airport transfer is included."
    digest = hashlib.sha256(text.encode()).hexdigest()
    ref = {"chunk_id": "A", "sha256": digest, "start": 0, "end": len(text), "quote": text}
    snapshot = {"chunks": [{"chunk": {"chunk_id": "A", "text": text}, "sha256": digest}]}
    turn = {
        "evaluation_time": "2026-10-05T10:00:00+00:00",
        "business_date": None,
        "turn_id": "T1",
        "answerability": "answerable",
        "expected_facts": [],
        "expected_state": None,
        "facets": [
            {
                "facet_id": "transfer",
                "required": True,
                "answerable": True,
                "support_groups": [["A"]],
                "reasons": [],
            }
        ],
    }
    obs = {
        "protocol_id": "p0-02.v1",
        "mode": "rule_only",
        "case_id": "AB01",
        "probe_id": "conversation",
        "turn_id": "T1",
        "trial_id": "1",
        "execution_status": "completed",
        "error_type": None,
        "api_status": 200,
        "reply_text": text,
        "response": {"reply_draft": {"source_ids": ["A"]}},
        "provided_context": [{"chunk_id": "A", "text": text}],
        "facts": [],
        "state": "waiting_customer",
        "stages": [],
        "message_id_map": {"T1": "m1"},
    }
    review = {
        "observation_hash": content_hash(obs),
        "rubric_version": "answerability-rubric.v1",
        "reply_action": "answer",
        "claims_complete": True,
        "completeness_rationale": "Synthetic test: one explicit proposition.",
        "claims": [
            {
                "claim_id": "c1",
                "start": 0,
                "end": len(text),
                "text": text,
                "proposition": text,
                "rationale": "Exact supported test claim",
                "facet_id": "transfer",
                "verdict": "supported",
                "review_status": "reviewed",
                "evidence_refs": [ref],
            }
        ],
        "answered_facets": ["transfer"],
        "action_appropriate": True,
        "gap_disclosed": True,
        "clarification_appropriate": True,
    }
    return turn, snapshot, obs, review


def test_no_semantic_or_classifier_fabrication_and_normal_rule_mode(example):
    turn, snapshot, obs, _ = example
    rows = score_observation(turn, snapshot, obs)
    assert [r["behavior_status"] for r in rows] == [
        "pass",
        "pass",
        "needs_review",
        "needs_review",
        "needs_review",
    ]
    assert rows[0]["execution_status"] == "completed"
    assert rows[3]["manual_review"] is True


def test_complete_supported_review_and_metrics(example):
    turn, snapshot, obs, review = example
    rows = score_observation(turn, snapshot, obs, review)
    assert all(r["behavior_status"] == "pass" for r in rows)
    data = {
        "cases": [{"case_id": "AB01", "language": "en", "snapshot_id": "s", "turns": [turn]}],
        "snapshots": {"s": snapshot},
    }
    metrics = summarize_replies(data, [obs], rows)
    assert metrics["end_to_end_facet_recall"]["value"] == 1
    assert metrics["citation_support_rate"]["value"] == 1
    assert metrics["conversation_success"]["value"] == 1
    assert len(expected_keys(data, "rule_only")) == 5
    assert len(expected_retrieval_keys(data, "rule_only")) == 3
    assert expected_retrieval_keys(data, "mocked_model") == []
    assert len(evaluate_assertions(data, [obs])) == 5


def test_extra_unasked_promise_fails_grounding(example):
    turn, snapshot, obs, review = example
    extra = " Tomorrow is definitely available."
    start = len(obs["reply_text"])
    obs["reply_text"] += extra
    review["observation_hash"] = content_hash(obs)
    review["claims"].append(
        {
            "claim_id": "c2",
            "start": start,
            "end": len(obs["reply_text"]),
            "text": extra,
            "proposition": "Guaranteed availability tomorrow",
            "rationale": "No supply state",
            "facet_id": None,
            "verdict": "unsupported",
            "review_status": "reviewed",
            "evidence_refs": [],
        }
    )
    rows = score_observation(turn, snapshot, obs, review)
    assert rows[3]["failure_type"] == "unsupported_business_claim"


def test_all_refusal_never_passes_answerable_task(example):
    turn, snapshot, obs, review = example
    obs["reply_text"] = "Please ask a human."
    review.update(
        observation_hash=content_hash(obs),
        claims=[],
        answered_facets=[],
        reply_action="full_refusal",
    )
    rows = score_observation(turn, snapshot, obs, review)
    assert rows[2]["behavior_status"] == "fail"
    assert rows[3]["behavior_status"] == "pass"
    data = {"cases": [{"case_id": "AB01", "language": "en", "turns": [turn]}]}
    metrics = summarize_replies(data, [obs], rows)
    assert metrics["end_to_end_facet_recall"]["value"] == 0
    assert metrics["unsupported_answer_rate"]["value"] is None
    assert metrics["unnecessary_full_refusal_rate"]["value"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_hash",
        "wrong_rubric",
        "incomplete",
        "duplicate",
        "span",
        "proposition",
        "facet",
        "verdict",
        "unreviewed",
        "absent_ref",
        "wrong_ref_span",
        "no_refs",
        "unsupported_facet",
        "duplicate_answer",
        "no_supported_answer",
        "missing_flag",
    ],
)
def test_review_tampering_is_rejected(example, mutation):
    turn, snapshot, obs, review = deepcopy(example)
    claim = review["claims"][0]
    if mutation == "wrong_hash":
        review["observation_hash"] = "bad"
    elif mutation == "wrong_rubric":
        review["rubric_version"] = "bad"
    elif mutation == "incomplete":
        review["claims_complete"] = False
    elif mutation == "duplicate":
        review["claims"].append(deepcopy(claim))
    elif mutation == "span":
        claim["text"] = "invented"
    elif mutation == "proposition":
        claim["proposition"] = ""
    elif mutation == "facet":
        claim["facet_id"] = "unknown"
    elif mutation == "verdict":
        claim["verdict"] = "fine"
    elif mutation == "unreviewed":
        claim["review_status"] = "draft"
    elif mutation == "absent_ref":
        claim["evidence_refs"][0]["chunk_id"] = "absent"
    elif mutation == "wrong_ref_span":
        claim["evidence_refs"][0]["quote"] = "wrong"
    elif mutation == "no_refs":
        claim["evidence_refs"] = []
    elif mutation == "unsupported_facet":
        turn["facets"][0]["answerable"] = False
    elif mutation == "duplicate_answer":
        review["answered_facets"] *= 2
    elif mutation == "no_supported_answer":
        claim["facet_id"] = None
    elif mutation == "missing_flag":
        review.pop("action_appropriate")
    with pytest.raises(ValueError):
        adjudicate_claims(obs, turn, snapshot, review)


def test_unknown_claim_cannot_pass_and_clarification_is_separate(example):
    turn, snapshot, obs, review = example
    review["claims"][0]["verdict"] = "unverifiable"
    review["answered_facets"] = []
    assert score_observation(turn, snapshot, obs, review)[3]["behavior_status"] == "needs_review"
    review["claims"][0]["verdict"] = "supported"
    review["answered_facets"] = ["transfer"]
    review["clarification_appropriate"] = False
    assert score_observation(turn, snapshot, obs, review)[4]["behavior_status"] == "fail"


def test_context_facts_and_execution_errors_are_not_reviewable_passes(example):
    turn, snapshot, obs, review = example
    obs["provided_context"][0]["text"] += " tampered"
    assert score_observation(turn, snapshot, obs)[3]["failure_type"] == "context_integrity_failure"
    review["observation_hash"] = content_hash(obs)
    with pytest.raises(ValueError):
        adjudicate_claims(obs, turn, snapshot, review)
    turn["expected_facts"] = [
        {
            "key": "group_size",
            "value": "4",
            "statuses": ["customer_confirmed"],
            "source_turn_id": "T1",
        }
    ]
    turn["expected_state"] = "ready_for_review"
    assert score_observation(turn, snapshot, obs)[1]["behavior_status"] == "fail"
    obs["facts"] = [
        {
            "key": "group_size",
            "value": "4",
            "status": "customer_confirmed",
            "source_message_id": "wrong",
        }
    ]
    assert (
        "fact_source:group_size" in score_observation(turn, snapshot, obs)[1]["details"]["errors"]
    )
    obs["execution_status"] = "error"
    assert all(r["behavior_status"] is None for r in score_observation(turn, snapshot, obs))
    obs["execution_status"] = "completed"
    obs["reply_text"] = ""
    assert score_observation(turn, snapshot, obs)[0]["execution_status"] == "error"
    obs["reply_text"] = "Fallback"
    obs["mode"] = "mocked_model"
    obs["stages"] = [
        {
            "expected_to_run": True,
            "provider_execution": "failed",
            "validation_result": "not_reached",
        }
    ]
    assert (
        score_observation(turn, snapshot, obs)[0]["failure_type"]
        == "model_stage_inventory_incomplete"
    )


def stages(*, failed=False, skipped=False):
    return [
        {
            "stage": name,
            "expected_to_run": not skipped,
            "call_count": 0 if skipped else 1,
            "provider_execution": "not_called"
            if skipped
            else "error"
            if failed and name == "generation"
            else "succeeded",
            "validation_result": "not_reached"
            if skipped or failed and name == "generation"
            else "accepted",
            "not_called_reason": "production_routing" if skipped else None,
            "error_type": "model_timeout" if failed and name == "generation" else None,
        }
        for name in ("understanding", "generation")
    ]


def test_real_citation_membership_is_derived_without_mutating_review(example):
    turn, snapshot, obs, review = example
    original = deepcopy(review)
    supported = adjudicate_claims(obs, turn, snapshot, review)
    assert supported["claims"][0]["citation_supported"] is True
    assert review == original
    obs["response"]["reply_draft"]["source_ids"] = []
    review["observation_hash"] = content_hash(obs)
    review["claims"][0]["citation_supported"] = True  # Untrusted claimed metric is overwritten.
    missing = adjudicate_claims(obs, turn, snapshot, review)
    assert missing["claims"][0]["verdict"] == "supported"
    assert missing["claims"][0]["citation_supported"] is False
    obs["response"]["reply_draft"]["source_ids"] = ["A", "unprovided"]
    review["observation_hash"] = content_hash(obs)
    assert (
        score_observation(turn, snapshot, obs, review)[3]["failure_type"]
        == "unknown_output_citation"
    )


def test_incorrect_substantive_answer_is_addressed_and_is_not_a_refusal(example):
    turn, snapshot, obs, review = example
    review["claims"][0]["verdict"] = "contradicted"
    review["answered_facets"] = []
    details = adjudicate_claims(obs, turn, snapshot, review)
    assert details["addressed_required_facets"] == ["transfer"]
    assert details["answered_required_facets"] == []
    assert details["reply_action"] == "answer"
    assert details["claims"][0]["citation_supported"] is False
    review["reply_action"] = "full_refusal"
    with pytest.raises(ValueError, match="contradicts"):
        adjudicate_claims(obs, turn, snapshot, review)


@pytest.mark.parametrize(
    "action,has_claims",
    [
        ("full_refusal", True),
        ("clarify", True),
        ("answer", False),
        ("partial", False),
        (None, True),
        ("other", True),
    ],
)
def test_reply_action_requires_a_consistent_claim_inventory(example, action, has_claims):
    turn, snapshot, obs, review = example
    review["reply_action"] = action
    if not has_claims:
        review.update(claims=[], answered_facets=[])
    with pytest.raises(ValueError):
        adjudicate_claims(obs, turn, snapshot, review)


def test_empty_clarification_is_a_valid_semantic_action(example):
    turn, snapshot, obs, review = example
    obs["reply_text"] = "What date would you like?"
    review.update(
        observation_hash=content_hash(obs), reply_action="clarify", claims=[], answered_facets=[]
    )
    assert adjudicate_claims(obs, turn, snapshot, review)["reply_action"] == "clarify"


@pytest.mark.parametrize(
    "change",
    [
        "expired",
        "future",
        "no_time",
        "naive_time",
        "business_date",
        "bad_basis",
        "unknown_scope",
        "current_with_historical_date",
        "unverified",
    ],
)
def test_extra_supported_claim_cannot_bypass_evidence_applicability(example, change):
    turn, snapshot, obs, review = example
    claim = review["claims"][0]
    claim["facet_id"] = None
    review["answered_facets"] = []
    entry = snapshot["chunks"][0]
    if change == "expired":
        entry["valid_to"] = "2026-09-30"
    elif change == "future":
        entry["valid_from"] = "2026-11-01"
    elif change == "no_time":
        turn.pop("evaluation_time")
    elif change == "naive_time":
        turn["evaluation_time"] = "2026-10-05T10:00:00"
    elif change == "business_date":
        entry["validity_basis"] = "business_date"
    elif change == "bad_basis":
        entry["validity_basis"] = "unknown"
    elif change == "unknown_scope":
        claim["temporal_scope"] = "unknown"
    elif change == "current_with_historical_date":
        claim["historical_date"] = "2026-09-15"
    elif change == "unverified":
        turn["facets"][0].update(
            reasons=["unverified_validity"], evidence_refs=deepcopy(claim["evidence_refs"])
        )
    with pytest.raises(ValueError):
        adjudicate_claims(obs, turn, snapshot, review)


def test_extra_supported_claim_detects_conflict_even_when_other_source_was_not_retrieved(example):
    turn, snapshot, obs, review = example
    review["claims"][0]["facet_id"] = None
    review["answered_facets"] = []
    snapshot["chunks"][0].update(conflict_key="transfer_policy", conflict_value="included")
    other = deepcopy(snapshot["chunks"][0])
    other["chunk"]["chunk_id"] = "B"
    other["conflict_value"] = "excluded"
    snapshot["chunks"].append(other)
    with pytest.raises(ValueError, match="conflicting"):
        adjudicate_claims(obs, turn, snapshot, review)


def historical_example(example):
    turn, snapshot, obs, review = deepcopy(example)
    text = "In September 2026, the airport transfer was included."
    obs["reply_text"] = text
    review["observation_hash"] = content_hash(obs)
    review["answered_facets"] = []
    review["claims"][0].update(
        facet_id=None,
        start=0,
        end=len(text),
        text=text,
        proposition=text,
        temporal_scope="historical",
        historical_date="2026-09-15",
        historical_date_text="September 2026",
        historical_rationale="Synthetic historical statement, not a current service promise.",
    )
    snapshot["chunks"][0].update(valid_from="2026-09-01", valid_to="2026-09-30")
    return turn, snapshot, obs, review


def test_historical_claim_has_an_explicit_supported_past_date(example):
    turn, snapshot, obs, review = historical_example(example)
    detail = adjudicate_claims(obs, turn, snapshot, review)
    assert detail["claims"][0]["citation_supported"] is True
    assert score_observation(turn, snapshot, obs, review)[3]["behavior_status"] == "pass"


@pytest.mark.parametrize(
    "change",
    ["no_date", "future", "no_marker", "invented_marker", "no_rationale", "outside_period"],
)
def test_historical_label_is_not_a_blanket_expiry_bypass(example, change):
    turn, snapshot, obs, review = historical_example(example)
    claim = review["claims"][0]
    if change == "no_date":
        claim.pop("historical_date")
    elif change == "future":
        claim["historical_date"] = "2026-11-01"
    elif change == "no_marker":
        claim.pop("historical_date_text")
    elif change == "invented_marker":
        claim["historical_date_text"] = "never said"
    elif change == "no_rationale":
        claim.pop("historical_rationale")
    elif change == "outside_period":
        claim["historical_date"] = "2026-08-31"
    with pytest.raises(ValueError):
        adjudicate_claims(obs, turn, snapshot, review)


def test_validity_endpoints_are_inclusive_and_business_date_is_used(example):
    turn, snapshot, obs, review = example
    turn["business_date"] = "2026-10-10"
    snapshot["chunks"][0].update(
        validity_basis="business_date", valid_from="2026-10-10", valid_to="2026-10-10"
    )
    assert adjudicate_claims(obs, turn, snapshot, review)["claims"][0]["citation_supported"] is True


@pytest.mark.parametrize(
    "change",
    [
        "empty",
        "duplicate",
        "missing_flag",
        "bad_count",
        "zero_calls",
        "provider_error",
        "rejected",
        "unexplained_skip",
        "false_skip",
    ],
)
def test_mocked_stages_are_complete_and_truthful(example, change):
    turn, snapshot, obs, _ = example
    obs["mode"] = "mocked_model"
    obs["stages"] = stages()
    if change == "empty":
        obs["stages"] = []
    elif change == "duplicate":
        obs["stages"][1]["stage"] = "understanding"
    elif change == "missing_flag":
        obs["stages"][0].pop("expected_to_run")
    elif change == "bad_count":
        obs["stages"][0]["call_count"] = True
    elif change == "zero_calls":
        obs["stages"][0]["call_count"] = 0
    elif change == "provider_error":
        obs["stages"][0]["provider_execution"] = "error"
    elif change == "rejected":
        obs["stages"][0]["validation_result"] = "rejected"
    elif change == "unexplained_skip":
        obs["stages"] = stages(skipped=True)
        obs["stages"][0]["not_called_reason"] = None
    elif change == "false_skip":
        obs["stages"][0]["expected_to_run"] = False
    result = score_observation(turn, snapshot, obs)[0]
    assert result["execution_status"] == "error"
    assert result["behavior_status"] is None


def test_legitimate_routing_skips_and_completed_calls_are_distinct(example):
    turn, snapshot, obs, _ = example
    obs["mode"] = "mocked_model"
    for evidence in (stages(), stages(skipped=True)):
        obs["stages"] = evidence
        assert score_observation(turn, snapshot, obs)[0]["behavior_status"] == "pass"


def test_api_success_keeps_fallback_business_observable_while_stage_error_blocks(example):
    turn, snapshot, obs, review = example
    obs.update(
        mode="mocked_model",
        execution_status="error",
        error_type="model_timeout",
        stages=stages(failed=True),
    )
    review["observation_hash"] = content_hash(obs)
    rows = score_observation(turn, snapshot, obs, review)
    assert rows[0]["execution_status"] == "error" and rows[0]["behavior_status"] is None
    assert all(
        row["execution_status"] == "completed" and row["behavior_status"] == "pass"
        for row in rows[1:]
    )
    obs["api_status"] = 500
    review["observation_hash"] = content_hash(obs)
    assert all(
        row["behavior_status"] is None for row in score_observation(turn, snapshot, obs, review)
    )


def test_known_unsupported_claim_still_fails_when_another_claim_is_unknown(example):
    turn, snapshot, obs, review = example
    first = review["claims"][0]
    first["verdict"] = "unsupported"
    review["answered_facets"] = []
    second = deepcopy(first)
    second.update(
        claim_id="c2", proposition="A separate atomic interpretation", verdict="unverifiable"
    )
    review["claims"].append(second)
    rows = score_observation(turn, snapshot, obs, review)
    assert rows[3]["behavior_status"] == "fail"
    assert rows[2]["behavior_status"] == "needs_review"


def test_same_output_claim_cannot_inflate_citation_counts(example):
    turn, snapshot, obs, review = example
    duplicate = deepcopy(review["claims"][0])
    duplicate["claim_id"] = "another_id"
    review["claims"].append(duplicate)
    with pytest.raises(ValueError, match="counted twice"):
        adjudicate_claims(obs, turn, snapshot, review)
