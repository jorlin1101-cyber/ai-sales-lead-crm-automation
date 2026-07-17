import pytest
from pydantic import ValidationError

from lead_cleaner.rag.eval_schemas import RagEvalCase


def test_rag_eval_case_accepts_valid_data() -> None:
    eval_case = RagEvalCase(
        query_id="yunnan_family_001",
        query="Is Yunnan good for families with children?",
        expected_region="yunnan",
        expected_doc_type="product",
        expected_source_titles=["Yunnan Family Tour"],
        expected_sections=["Suitable For", "Key Experiences", "Overview"],
    )

    assert eval_case.query_id == "yunnan_family_001"
    assert eval_case.expected_region == "yunnan"
    assert eval_case.expected_doc_type == "product"
    assert eval_case.expected_source_titles == ["Yunnan Family Tour"]
    assert eval_case.expected_sections == [
        "Suitable For",
        "Key Experiences",
        "Overview",
    ]


def test_rag_eval_case_rejects_empty_query() -> None:
    with pytest.raises(ValidationError):
        RagEvalCase(
            query_id="yunnan_family_001",
            query="",
            expected_region="yunnan",
            expected_doc_type="product",
            expected_source_titles=["Yunnan Family Tour"],
            expected_sections=["Suitable For"],
        )


def test_rag_eval_case_rejects_empty_expected_sections() -> None:
    with pytest.raises(ValidationError):
        RagEvalCase(
            query_id="yunnan_family_001",
            query="Is Yunnan good for families with children?",
            expected_region="yunnan",
            expected_doc_type="product",
            expected_source_titles=["Yunnan Family Tour"],
            expected_sections=[],
        )
