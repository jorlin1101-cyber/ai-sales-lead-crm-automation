import math

import pytest

from lead_cleaner.answerability_evaluation.metrics import (
    ratio,
    score_retrieval,
    summarize_replies,
    summarize_retrieval,
)


def turn(facets=None, judgments=None):
    return {
        "turn_id": "T1",
        "answerability": "answerable",
        "facets": facets
        or [
            {
                "facet_id": "transfer",
                "required": True,
                "answerable": True,
                "support_groups": [["A"]],
                "reasons": [],
            }
        ],
        "judgments": judgments if judgments is not None else {"A": 3, "B": 1, "C": 0, "D": 0},
    }


def results(*ids):
    return [{"chunk_id": i} for i in ids]


def test_k_boundary_dedup_and_exact_ndcg():
    value = score_retrieval(turn(), results("B", "C", "D", "A"))
    assert value["supported_facet_hit"]["value"] == 0
    assert value["support_completion_rr"]["value"] == 0
    assert value["ndcg"]["value"] == pytest.approx(1 / (7 + 1 / math.log2(3)))
    repeated = score_retrieval(turn(), results("B", "B", "B", "A"))
    assert repeated["ndcg"]["value"] == value["ndcg"]["value"]
    assert repeated["answerable_facet_recall"]["value"] == 0
    with pytest.raises(ValueError):
        score_retrieval(turn(), [], k=0)


def test_support_combinations_and_optional_facets():
    data = turn(
        facets=[
            {
                "facet_id": "transfer",
                "required": True,
                "answerable": True,
                "support_groups": [["A", "B"]],
                "reasons": [],
            },
            {
                "facet_id": "optional",
                "required": False,
                "answerable": True,
                "support_groups": [["C"]],
                "reasons": [],
            },
        ]
    )
    assert score_retrieval(data, results("A"))["supported_facet_hit"]["value"] == 0
    complete = score_retrieval(data, results("A", "B"))
    assert complete["support_completion_rr"]["value"] == 0.5
    assert complete["answerable_facet_recall"]["numerator"] == 1
    assert complete["answerable_facet_recall"]["denominator"] == 1


def test_unknown_ndcg_is_not_zero_or_excluded():
    scored = score_retrieval(turn(), results("A", "unknown"))
    assert scored["supported_facet_hit"]["value"] == 1
    assert scored["support_completion_rr"]["value"] == 1
    assert scored["ndcg"]["value"] is None
    assert scored["ndcg"]["denominator"] == 1
    assert scored["ndcg"]["needs_review_count"] == 1
    assert scored["unjudged_rate"]["value"] == 0.5
    missed = score_retrieval(turn(), results("unknown"))
    assert missed["supported_facet_hit"]["applicability"] == "incomplete_judgments"


def test_unanswerable_na_and_empty_retrieval():
    data = turn(
        facets=[
            {
                "facet_id": "live",
                "required": True,
                "answerable": False,
                "support_groups": [],
                "reasons": ["requires_live_supply"],
            }
        ],
        judgments={},
    )
    for name, metric in score_retrieval(data, []).items():
        assert metric["value"] is None, name
        assert metric["denominator"] == 0
    assert score_retrieval(turn(), [])["supported_facet_hit"]["value"] == 0


@pytest.mark.parametrize("status,field", [("error", "error_count"), ("not_run", "not_run_count")])
def test_execution_failure_does_not_shrink_planned_cohort(status, field):
    score = score_retrieval(turn(), [], execution_status=status)
    assert score["supported_facet_hit"]["denominator"] == 1
    assert score["supported_facet_hit"][field] == 1
    assert score["supported_facet_hit"]["value"] is None


def test_micro_macro_and_fixed_unknown_aggregate():
    first = turn(
        facets=[
            {
                "facet_id": i,
                "required": True,
                "answerable": True,
                "support_groups": [[i]],
                "reasons": [],
            }
            for i in ["A", "B"]
        ]
    )
    rows = [
        {"path": "raw_query", "metrics": score_retrieval(first, results("A"))},
        {"path": "raw_query", "metrics": score_retrieval(turn(), results("A"))},
    ]
    score = summarize_retrieval(rows)["raw_query"]
    assert score["answerable_facet_recall"]["value"] == pytest.approx(2 / 3)
    assert score["answerable_facet_recall_macro"]["value"] == 0.75
    rows.append({"path": "raw_query", "metrics": score_retrieval(turn(), results("unjudged"))})
    score = summarize_retrieval(rows)["raw_query"]
    assert score["ndcg"]["denominator"] == 3
    assert score["ndcg"]["value"] is None
    assert ratio(0, 0)["value"] is None


def test_reply_success_denominator_includes_missing_and_intermediate_failure():
    turns = [turn(), {**turn(), "turn_id": "T2"}, {**turn(), "turn_id": "T3"}]
    data = {"cases": [{"case_id": "AB21", "language": "zh", "turns": turns}]}
    obs = [
        {"case_id": "AB21", "turn_id": "T1", "execution_status": "completed"},
        {"case_id": "AB21", "turn_id": "T3", "execution_status": "completed"},
    ]
    assertions = [
        {
            "case_id": "AB21",
            "turn_id": t,
            "assertion_id": name,
            "behavior_status": "fail" if t == "T1" else "pass",
        }
        for t in ["T1", "T3"]
        for name in ["execution", "facts_state", "answer_content", "grounding", "clarification"]
    ]
    metrics = summarize_replies(data, obs, assertions)
    assert metrics["all"]["denominator"] == 3
    assert metrics["all"]["numerator"] == 1
    assert metrics["all"]["not_run_count"] == 1
    assert metrics["conversation_success"]["value"] == 0
    assert metrics["unsupported_answer_rate"]["value"] is None
    assert metrics["predicted_answerability"]["applicability"] == "not_observed"


def test_unreviewed_counts_use_turn_and_facet_units_separately():
    current = turn(
        facets=[
            {
                "facet_id": i,
                "required": True,
                "answerable": True,
                "support_groups": [[i]],
                "reasons": [],
            }
            for i in ["A", "B"]
        ]
    )
    data = {"cases": [{"case_id": "AB01", "language": "zh", "turns": [current]}]}
    obs = [{"case_id": "AB01", "turn_id": "T1", "execution_status": "completed"}]
    rows = [
        {"case_id": "AB01", "turn_id": "T1", "assertion_id": n, "behavior_status": "needs_review"}
        for n in ["execution", "facts_state", "answer_content", "grounding", "clarification"]
    ]
    metrics = summarize_replies(data, obs, rows)
    assert metrics["all"]["adjudicated_count"] == 0
    assert metrics["all"]["needs_review_count"] == 1
    assert metrics["all"]["value"] is None
    assert metrics["end_to_end_facet_recall"]["needs_review_count"] == 2
    assert metrics["end_to_end_facet_recall"]["denominator"] == 2


def test_wrong_answer_is_not_a_refusal_or_an_omission():
    data = {"cases": [{"case_id": "AB01", "language": "en", "turns": [turn()]}]}
    obs = [{"case_id": "AB01", "turn_id": "T1", "execution_status": "completed"}]
    details = {
        "claims_complete": True,
        "claims": [{"verdict": "contradicted", "citation_supported": False}],
        "context_supported_facets": ["transfer"],
        "addressed_required_facets": ["transfer"],
        "answered_required_facets": [],
        "reply_action": "answer",
    }
    rows = [
        {
            "case_id": "AB01",
            "turn_id": "T1",
            "assertion_id": n,
            "behavior_status": "fail",
            "details": details,
        }
        for n in ["execution", "facts_state", "answer_content", "grounding", "clarification"]
    ]
    metrics = summarize_replies(data, obs, rows)
    assert metrics["unsupported_answer_rate"]["value"] == 1
    assert metrics["unnecessary_full_refusal_rate"]["value"] == 0
    assert metrics["context_supported_omission_rate"]["value"] == 0
    assert metrics["citation_support_rate"]["value"] == 0
    obs[0].update(execution_status="error", api_status=200, reply_text="safe fallback")
    details["claims"] = []
    details["reply_action"] = "full_refusal"
    fallback = summarize_replies(data, obs, rows)
    assert fallback["fallback_safety"]["value"] == 1
    assert fallback["all"]["value"] == 0
    assert fallback["all"]["error_count"] == 1


def test_v2_groups_keep_errors_unknown_and_absent_units_in_each_plan():
    from lead_cleaner.answerability_evaluation.metrics import aggregate_metrics

    cases = [
        {"case_id": "H", "evaluation_group": "handbook", "language": "zh", "turns": [turn()]},
        {
            "case_id": "S",
            "evaluation_group": "synthetic_special",
            "language": "en",
            "turns": [turn()],
        },
    ]
    data = {"protocol_id": "p0-02.v2", "cases": cases}
    obs = [{"case_id": "H", "turn_id": "T1", "execution_status": "error"}]
    result = aggregate_metrics(data, obs, [], [], "rule_only")
    assert "replies" not in result and "retrieval" not in result
    assert result["cross_group_accuracy"] == "not_computed"
    for name in ["handbook", "synthetic_special"]:
        group = result["groups"][name]
        assert group["replies"]["all"]["denominator"] == 1
        assert group["counts"]["retrieval_units"] == 3
        assert group["counts"]["observed_retrieval_units"] == 0
        assert group["replies"]["state:partial"]["applicability"] == "not_applicable"
        for metrics in group["retrieval"].values():
            assert metrics["supported_facet_hit"]["denominator"] == 1
            assert metrics["supported_facet_hit"]["not_run_count"] == 1
            assert metrics["supported_facet_hit"]["value"] is None
    assert result["groups"]["handbook"]["replies"]["all"]["error_count"] == 1
    assert result["groups"]["synthetic_special"]["replies"]["all"]["not_run_count"] == 1
    obs[0]["execution_status"] = "completed"
    pending = summarize_replies(data, obs, [])
    assert pending["groups"]["handbook"]["all"]["value"] is None
    assert pending["groups"]["handbook"]["all"]["needs_review_count"] == 1
    with pytest.raises(ValueError):
        summarize_replies({**data, "protocol_id": "future"}, [], [])
    cases[0]["evaluation_group"] = "unknown"
    with pytest.raises(ValueError, match="evaluation group"):
        summarize_replies(data, [], [])


def test_v2_retrieval_group_aggregation_rejects_unknown_duplicate_or_wrong_mode():
    from lead_cleaner.answerability_evaluation.metrics import aggregate_metrics

    data = {
        "protocol_id": "p0-02.v2",
        "cases": [
            {"case_id": "H", "evaluation_group": "handbook", "language": "en", "turns": [turn()]}
        ],
    }
    row = {
        "case_id": "H",
        "path": "raw_query",
        "metrics": score_retrieval(turn(), results("unknown")),
    }
    score = aggregate_metrics(data, [], [], [row], "rule_only")
    assert score["groups"]["handbook"]["retrieval"]["raw_query"]["ndcg"]["needs_review_count"] == 1
    for rows in [[row, row], [{**row, "case_id": "unknown"}]]:
        with pytest.raises(ValueError, match="identities"):
            aggregate_metrics(data, [], [], rows, "rule_only")
    with pytest.raises(ValueError, match="rule_only"):
        aggregate_metrics(data, [], [], [row], "mocked_model")
    with pytest.raises(ValueError, match="rule_only"):
        aggregate_metrics(data, [], [], [], "live")
    empty = aggregate_metrics(data, [], [], [], "mocked_model")
    assert empty["retrieval_applicability"] == "not_applicable"
    assert empty["groups"]["handbook"]["counts"]["retrieval_units"] == 0
