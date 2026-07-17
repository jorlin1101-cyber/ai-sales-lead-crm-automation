import pytest

from lead_cleaner.rag.eval_runner import has_expected_match, is_expected_match, evaluate_match_detail
from lead_cleaner.rag.eval_schemas import RagEvalCase
from lead_cleaner.rag.schemas import RetrievedChunk


def make_eval_case() -> RagEvalCase:
    return RagEvalCase(
        query_id="yunnan_family_001",
        query="Is Yunnan good for families with children?",
        expected_region="yunnan",
        expected_doc_type="product",
        expected_source_titles=["Yunnan Family Tour"],
        expected_sections=["Suitable For", "Key Experiences", "Overview"],
    )


def make_retrieved_chunk(
    source_title: str = "Yunnan Family Tour",
    section: str = "Suitable For",
    doc_type: str = "product",
    region: str = "yunnan",
    rank: int = 1,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk_{rank}",
        source_type="notion_page",
        notion_page_id="page_001",
        source_title=source_title,
        source_path="Products / Yunnan Family Tour",
        doc_type=doc_type,
        region=region,
        product_name="Yunnan Family Tour",
        section=section,
        text="Yunnan is suitable for families with children.",
        score=1.0,
        rank=rank,
        retrieval_source="fusion",
    )


def test_is_expected_match_returns_true_when_all_fields_match() -> None:
    eval_case = make_eval_case()
    result = make_retrieved_chunk()

    assert is_expected_match(result=result, eval_case=eval_case) is True


def test_is_expected_match_returns_false_when_section_does_not_match() -> None:
    eval_case = make_eval_case()
    result = make_retrieved_chunk(section="Pricing Notes")

    assert is_expected_match(result=result, eval_case=eval_case) is False


def test_has_expected_match_checks_top_k_window() -> None:
    eval_case = make_eval_case()
    wrong_result = make_retrieved_chunk(section="Pricing Notes", rank=1)
    correct_result = make_retrieved_chunk(section="Suitable For", rank=2)

    results = [wrong_result, correct_result]

    assert has_expected_match(results=results, eval_case=eval_case, top_k=1) is False
    assert has_expected_match(results=results, eval_case=eval_case, top_k=2) is True


def test_has_expected_match_rejects_invalid_top_k() -> None:
    eval_case = make_eval_case()
    result = make_retrieved_chunk()

    with pytest.raises(ValueError):
        has_expected_match(results=[result], eval_case=eval_case, top_k=0)


def test_evaluate_match_detail_returns_all_hits_for_matching_result() -> None:
    eval_case = make_eval_case()
    result = make_retrieved_chunk()

    detail = evaluate_match_detail(result=result, eval_case=eval_case)

    assert detail.doc_type_hit is True
    assert detail.region_hit is True
    assert detail.source_title_hit is True
    assert detail.section_hit is True
    assert detail.overall_match is True


def test_evaluate_match_detail_marks_section_miss() -> None:
    eval_case = make_eval_case()
    result = make_retrieved_chunk(section="Pricing Notes")

    detail = evaluate_match_detail(result=result, eval_case=eval_case)

    assert detail.doc_type_hit is True
    assert detail.region_hit is True
    assert detail.source_title_hit is True
    assert detail.section_hit is False
    assert detail.overall_match is False
