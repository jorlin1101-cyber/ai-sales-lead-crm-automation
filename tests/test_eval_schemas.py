import pytest
from pydantic import ValidationError

from lead_cleaner.rag.eval_schemas import RagEvalCase


def valid_case_data() -> dict[str, object]:
    return {
        "query_id": "yunnan_family_001",
        "query": "Is Yunnan good for families with children?",
        "language": "en",
        "query_type": "single_intent",
        "facets": [
            {
                "facet_id": "family_fit",
                "description": "Whether the tour is suitable for a family.",
            }
        ],
        "judgments": [
            {
                "source_title": "Yunnan Family Tour",
                "section": "Suitable For",
                "relevance_grade": 3,
                "covers_facets": ["family_fit"],
                "reason": "Directly states who the tour is suitable for.",
            },
            {
                "source_title": "Yunnan Family Tour",
                "section": "Key Experiences",
                "relevance_grade": 2,
                "covers_facets": ["family_fit"],
                "reason": "Provides useful supporting family activity details.",
            },
        ],
    }


def test_rag_eval_case_accepts_paired_graded_judgments() -> None:
    eval_case = RagEvalCase.model_validate(valid_case_data())

    assert eval_case.query_id == "yunnan_family_001"
    assert eval_case.language == "en"
    assert eval_case.query_type == "single_intent"
    assert eval_case.facets[0].facet_id == "family_fit"
    assert eval_case.judgments[0].relevance_grade == 3
    assert eval_case.judgments[0].section == "Suitable For"


def test_rag_eval_case_accepts_an_explicit_grade_0_judgment() -> None:
    case_data = valid_case_data()
    judgments = case_data["judgments"]
    assert isinstance(judgments, list)
    judgments.append(
        {
            "source_title": "Travel Permit and Payment FAQ",
            "section": "Sales Notes",
            "relevance_grade": 0,
            "covers_facets": [],
            "reason": "Reviewed and found unrelated to family suitability.",
        }
    )

    eval_case = RagEvalCase.model_validate(case_data)

    assert eval_case.judgments[-1].relevance_grade == 0
    assert eval_case.judgments[-1].covers_facets == []


def test_grade_0_judgment_cannot_cover_a_facet() -> None:
    case_data = valid_case_data()
    judgments = case_data["judgments"]
    assert isinstance(judgments, list)
    judgments[1]["relevance_grade"] = 0

    with pytest.raises(ValidationError, match="grade-0 judgments must not cover"):
        RagEvalCase.model_validate(case_data)


def test_positive_judgment_must_cover_a_facet() -> None:
    case_data = valid_case_data()
    judgments = case_data["judgments"]
    assert isinstance(judgments, list)
    judgments[1]["covers_facets"] = []

    with pytest.raises(ValidationError, match="must cover a facet"):
        RagEvalCase.model_validate(case_data)


def test_rag_eval_case_rejects_extra_legacy_fields() -> None:
    case_data = valid_case_data()
    case_data["expected_sections"] = ["Suitable For"]

    with pytest.raises(ValidationError, match="extra_forbidden"):
        RagEvalCase.model_validate(case_data)


def test_rag_eval_case_rejects_empty_query() -> None:
    case_data = valid_case_data()
    case_data["query"] = ""

    with pytest.raises(ValidationError):
        RagEvalCase.model_validate(case_data)


def test_rag_eval_case_rejects_unknown_facet_reference() -> None:
    case_data = valid_case_data()
    judgments = case_data["judgments"]
    assert isinstance(judgments, list)
    judgments[0]["covers_facets"] = ["unknown_facet"]

    with pytest.raises(ValidationError, match="unknown facets"):
        RagEvalCase.model_validate(case_data)


def test_rag_eval_case_rejects_duplicate_title_section_pair() -> None:
    case_data = valid_case_data()
    judgments = case_data["judgments"]
    assert isinstance(judgments, list)
    judgments.append(judgments[0].copy())

    with pytest.raises(ValidationError, match="pairs must be unique"):
        RagEvalCase.model_validate(case_data)


def test_rag_eval_case_requires_a_grade_3_direct_answer() -> None:
    case_data = valid_case_data()
    judgments = case_data["judgments"]
    assert isinstance(judgments, list)
    for judgment in judgments:
        judgment["relevance_grade"] = 2

    with pytest.raises(ValidationError, match="grade-3 direct answer"):
        RagEvalCase.model_validate(case_data)


def test_every_facet_requires_grade_3_coverage() -> None:
    case_data = valid_case_data()
    facets = case_data["facets"]
    judgments = case_data["judgments"]
    assert isinstance(facets, list)
    assert isinstance(judgments, list)
    facets.append(
        {
            "facet_id": "relaxed_pace",
            "description": "Whether the itinerary can be relaxed.",
        }
    )
    judgments[1]["covers_facets"] = ["family_fit", "relaxed_pace"]

    with pytest.raises(ValidationError, match="every facet must be covered"):
        RagEvalCase.model_validate(case_data)
