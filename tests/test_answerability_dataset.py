"""Data-contract tests, including falsified labels and exact evidence boundaries."""

from copy import deepcopy
from pathlib import Path
import json

import pytest
from pydantic import ValidationError

from lead_cleaner.answerability_evaluation.dataset import load_dataset, validate_dataset
from lead_cleaner.answerability_evaluation.schemas import Case, Turn

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def documents():
    directory = ROOT / "data/answerability_eval"
    return (
        json.loads((directory / "cases.json").read_bytes()),
        json.loads((directory / "knowledge.json").read_bytes()),
    )


def test_complete_frozen_matrix_and_exact_hashes():
    result = load_dataset(ROOT)
    assert len(result["cases"]) == 24
    assert sum(len(case["turns"]) for case in result["cases"]) == 36
    assert len(result["snapshots"]) == 7
    assert all(case["review_status"] in {"draft", "reviewed"} for case in result["cases"])
    assert all(
        case["review_status"] != "reviewed" or case["review_evidence"] for case in result["cases"]
    )
    assert len(result["dataset_hash"]) == len(result["knowledge_hash"]) == 64
    assert load_dataset(ROOT) == result


def test_order_does_not_change_the_required_case_matrix(documents):
    cases, knowledge = documents
    cases["cases"].reverse()
    assert len(validate_dataset(cases, knowledge)["cases"]) == 24


def test_unanswerable_may_have_empty_judgments_but_not_empty_knowledge(documents):
    cases, knowledge = documents
    cases["cases"][12]["turns"][0]["judgments"] = {}
    result = validate_dataset(cases, knowledge)
    assert result["cases"][12]["turns"][0]["answerability"] == "unanswerable"
    assert result["snapshots"]["unrelated"]["chunks"]
    knowledge["snapshots"]["unrelated"]["chunks"] = []
    with pytest.raises(ValidationError):
        validate_dataset(cases, knowledge)


def test_optional_answer_does_not_change_required_facet_state(documents):
    raw = deepcopy(documents[0]["cases"][6]["turns"][0])
    raw["facets"][0]["required"] = False
    raw["answerability"] = "unanswerable"
    raw["expected_action"] = "clarify"
    assert Turn.model_validate(raw).answerability == "unanswerable"


def test_combination_support_is_not_inferred_from_a_single_positive_grade(documents):
    result = validate_dataset(*documents)
    turn = result["cases"][5]["turns"][0]
    assert turn["facets"][0]["support_groups"] == [["guide_eligibility", "guide_hours"]]
    assert turn["judgments"]["guide_eligibility"] == turn["judgments"]["guide_hours"] == 2
    assert turn["answerability"] == "answerable"


def test_no_answer_reasons_have_actual_reference_metadata(documents):
    result = validate_dataset(*documents)
    assert {"conflicting_evidence", "expired_evidence", "unverified_validity"} <= {
        reason
        for case in result["cases"]
        for turn in case["turns"]
        for facet in turn["facets"]
        for reason in facet["reasons"]
    }
    expired = result["snapshots"]["expired"]["chunks"][1]
    assert expired["valid_to"] == "2026-09-30"
    assert expired["chunk"]["last_edited_time"] != expired["valid_to"]


@pytest.mark.parametrize(
    "fault,match",
    [
        ("missing_case", "exactly AB01"),
        ("duplicate_case", "exactly AB01"),
        ("language_matrix", "10 zh"),
        ("turn_count", "first 18"),
        ("unknown_snapshot", "unknown snapshot"),
        ("snapshot_identity", "snapshot key"),
        ("duplicate_chunk", "duplicate chunk"),
        ("text_hash", "knowledge text hash"),
        ("reference_hash", "evidence hash"),
        ("reference_end", "character interval"),
        ("reference_quote", "evidence quote"),
        ("unknown_reference", "unknown chunk"),
        ("partial_grades", "complete snapshot"),
        ("empty_answerable_grades", "complete snapshot"),
        ("unknown_grade_chunk", "complete snapshot"),
        ("inapplicable_support", "inapplicable"),
        ("missing_support_date", "inapplicable"),
        ("expired_without_dates", "expired label"),
        ("expired_still_current", "expired label"),
        ("validity_gap_not_missing", "metadata gap"),
        ("conflict_same_values", "distinct applicable"),
        ("conflict_different_keys", "distinct applicable"),
        ("conflict_one_source", "distinct applicable"),
        ("missing_customer_present", "no missing required"),
        ("answerable_customer_missing", "lacks required customer"),
    ],
)
def test_cross_file_forgery_is_rejected(documents, fault, match):
    cases, knowledge = documents
    first = cases["cases"][0]["turns"][0]
    reference = first["facets"][0]["evidence_refs"][0]
    chunk = knowledge["snapshots"]["core"]["chunks"][0]
    if fault == "missing_case":
        cases["cases"].pop()
    elif fault == "duplicate_case":
        cases["cases"][1] = deepcopy(cases["cases"][0])
    elif fault == "language_matrix":
        cases["cases"][0]["language"] = "en"
    elif fault == "turn_count":
        cases["cases"][18]["turns"].pop()
    elif fault == "unknown_snapshot":
        cases["cases"][0]["snapshot_id"] = "absent"
    elif fault == "snapshot_identity":
        knowledge["snapshots"]["core"]["snapshot_id"] = "other"
    elif fault == "duplicate_chunk":
        knowledge["snapshots"]["core"]["chunks"].append(deepcopy(chunk))
    elif fault == "text_hash":
        chunk["chunk"]["text"] += " altered"
    elif fault == "reference_hash":
        reference["sha256"] = "0" * 64
    elif fault == "reference_end":
        reference["end"] += 1
    elif fault == "reference_quote":
        reference["quote"] = "a different exact quote"
    elif fault == "unknown_reference":
        first["facets"][0]["support_groups"] = [["absent"]]
        reference["chunk_id"] = "absent"
    elif fault == "partial_grades":
        first["judgments"].pop("quote")
    elif fault == "empty_answerable_grades":
        first["judgments"] = {}
    elif fault == "unknown_grade_chunk":
        first["judgments"]["absent"] = 0
    elif fault == "inapplicable_support":
        chunk["valid_to"] = "2026-09-30"
    elif fault == "missing_support_date":
        cases["cases"][18]["turns"][1]["business_date"] = None
    elif fault == "expired_without_dates":
        knowledge["snapshots"]["expired"]["chunks"][1]["valid_to"] = None
    elif fault == "expired_still_current":
        knowledge["snapshots"]["expired"]["chunks"][1]["valid_to"] = "2026-10-31"
    elif fault == "validity_gap_not_missing":
        knowledge["snapshots"]["unverified"]["chunks"][0]["valid_from"] = "2026-10-01"
    elif fault == "conflict_same_values":
        knowledge["snapshots"]["conflict"]["chunks"][2]["conflict_value"] = "full_refund"
    elif fault == "conflict_different_keys":
        knowledge["snapshots"]["conflict"]["chunks"][2]["conflict_key"] = "other_policy"
    elif fault == "conflict_one_source":
        cases["cases"][10]["turns"][0]["facets"][1]["evidence_refs"].pop()
    elif fault == "missing_customer_present":
        cases["cases"][8]["turns"][0]["customer_facts"] = [
            {"key": "departure_date", "value": "2026-10-10", "source_turn_id": "T1"}
        ]
    elif fault == "answerable_customer_missing":
        cases["cases"][18]["turns"][1]["customer_facts"] = []
    with pytest.raises(ValueError, match=match):
        validate_dataset(cases, knowledge)


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_state",
        "no_required",
        "duplicate_facet",
        "boolean_grade",
        "high_grade",
        "duplicate_reason",
        "empty_group",
        "duplicate_group",
        "duplicate_group_member",
        "missing_support_ref",
        "answerable_blocked",
        "unanswerable_without_reason",
        "timezone",
        "future_fact",
        "future_history",
        "wrong_order",
        "backwards_time",
        "fake_reviewed",
        "extra_field",
        "missing_customer_fields",
        "empty_quote",
        "reversed_interval",
    ],
)
def test_strict_case_contract_rejects_invalid_values(documents, fault):
    case = deepcopy(documents[0]["cases"][18])
    case.update(review_status="draft", review_evidence=[])
    first, second = case["turns"][:2]
    if fault == "wrong_state":
        first["answerability"] = "answerable"
    elif fault == "no_required":
        first["facets"][0]["required"] = False
    elif fault == "duplicate_facet":
        first["facets"].append(deepcopy(first["facets"][0]))
    elif fault == "boolean_grade":
        first["judgments"]["date_policy"] = True
    elif fault == "high_grade":
        first["judgments"]["date_policy"] = 4
    elif fault == "duplicate_reason":
        first["facets"][0]["reasons"] *= 2
    elif fault == "empty_group":
        second["facets"][0]["support_groups"] = [[]]
    elif fault == "duplicate_group":
        second["facets"][0]["support_groups"] *= 2
    elif fault == "duplicate_group_member":
        second["facets"][0]["support_groups"][0] *= 2
    elif fault == "missing_support_ref":
        second["facets"][0]["evidence_refs"] = []
    elif fault == "answerable_blocked":
        second["facets"][0]["reasons"] = ["missing_static_knowledge"]
    elif fault == "unanswerable_without_reason":
        first["facets"][0]["reasons"] = []
    elif fault == "timezone":
        first["evaluation_time"] = "2026-10-05T10:00:00"
    elif fault == "future_fact":
        first["customer_facts"] = [{"key": "group_size", "value": "8", "source_turn_id": "T3"}]
    elif fault == "future_history":
        first["visible_turn_ids"] = ["T3"]
    elif fault == "wrong_order":
        first["turn_id"] = "T2"
    elif fault == "backwards_time":
        second["evaluation_time"] = "2026-10-04T10:00:00+00:00"
    elif fault == "fake_reviewed":
        case["review_status"] = "reviewed"
    elif fault == "extra_field":
        case["secret_answer"] = "leak"
    elif fault == "missing_customer_fields":
        first["facets"][0]["required_customer_fields"] = []
    elif fault == "empty_quote":
        first["facets"][0]["evidence_refs"][0]["quote"] = ""
    elif fault == "reversed_interval":
        first["facets"][0]["evidence_refs"][0]["start"] = 9999
    with pytest.raises(ValidationError):
        Case.model_validate(case)
