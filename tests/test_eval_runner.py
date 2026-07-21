import pytest

from lead_cleaner.rag.eval_runner import (
    evaluate_match_detail,
    facet_recall_at_k,
    has_expected_match,
    has_expected_source,
    is_expected_match,
    ndcg_at_k,
    reciprocal_rank,
    unjudged_rate_at_k,
    validate_eval_cases_against_chunks,
)
from lead_cleaner.rag.eval_schemas import RagEvalCase
from lead_cleaner.rag.schemas import KnowledgeChunk, RetrievedChunk


def make_eval_case() -> RagEvalCase:
    return RagEvalCase.model_validate(
        {
            "query_id": "yunnan_family_price_001",
            "query": "Is Yunnan good for families and what affects the price?",
            "language": "en",
            "query_type": "multi_intent",
            "facets": [
                {
                    "facet_id": "family_fit",
                    "description": "Whether the tour is suitable for families.",
                },
                {
                    "facet_id": "quote_drivers",
                    "description": "What changes the quotation.",
                },
            ],
            "judgments": [
                {
                    "source_title": "Yunnan Family Tour",
                    "section": "Suitable For",
                    "relevance_grade": 3,
                    "covers_facets": ["family_fit"],
                    "reason": "Direct family suitability answer.",
                },
                {
                    "source_title": "Yunnan Family Tour",
                    "section": "Pricing Notes",
                    "relevance_grade": 3,
                    "covers_facets": ["quote_drivers"],
                    "reason": "Direct pricing answer.",
                },
                {
                    "source_title": "Yunnan Family Tour",
                    "section": "Key Experiences",
                    "relevance_grade": 2,
                    "covers_facets": ["family_fit"],
                    "reason": "Useful supporting family activity details.",
                },
                {
                    "source_title": "Travel Permit and Payment FAQ",
                    "section": "Sales Notes",
                    "relevance_grade": 0,
                    "covers_facets": [],
                    "reason": "Reviewed and found unrelated to this question.",
                },
            ],
        }
    )


def make_retrieved_chunk(
    source_title: str = "Yunnan Family Tour",
    section: str = "Suitable For",
    rank: int = 1,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk_{rank}_{section.lower().replace(' ', '_')}",
        source_type="notion_page",
        notion_page_id="page_001",
        source_title=source_title,
        source_path="Products / Yunnan Family Tour",
        doc_type="product",
        region="yunnan",
        product_name="Yunnan Family Tour",
        section=section,
        text="Evaluation knowledge text.",
        score=1.0,
        rank=rank,
        retrieval_source="fusion",
    )


def make_knowledge_chunk(
    source_title: str,
    section: str,
    chunk_index: int,
) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=f"chunk_{chunk_index}",
        source_type="notion_page",
        notion_page_id="page_001",
        source_title=source_title,
        source_path="Products / Yunnan Family Tour",
        doc_type="product",
        region="yunnan",
        product_name="Yunnan Family Tour",
        section=section,
        chunk_index=chunk_index,
        text="Evaluation knowledge text.",
        last_edited_time="2026-07-21T00:00:00Z",
    )


def test_direct_judgment_is_an_expected_match() -> None:
    detail = evaluate_match_detail(make_retrieved_chunk(), make_eval_case())

    assert detail.relevance_grade == 3
    assert detail.judged is True
    assert detail.relevant_match is True
    assert detail.direct_match is True
    assert detail.source_match is True
    assert detail.covers_facets == ("family_fit",)
    assert detail.overall_match is True


def test_grade_2_judgment_is_relevant_but_not_direct() -> None:
    result = make_retrieved_chunk(section="Key Experiences")
    detail = evaluate_match_detail(result, make_eval_case())

    assert detail.relevance_grade == 2
    assert detail.relevant_match is True
    assert detail.direct_match is False
    assert is_expected_match(result, make_eval_case()) is False


def test_unjudged_section_in_a_relevant_source_is_only_a_source_match() -> None:
    detail = evaluate_match_detail(
        make_retrieved_chunk(section="Departure Notes"),
        make_eval_case(),
    )

    assert detail.relevance_grade == 0
    assert detail.judged is False
    assert detail.direct_match is False
    assert detail.source_match is True


def test_explicit_grade_0_is_judged_but_not_relevant() -> None:
    detail = evaluate_match_detail(
        make_retrieved_chunk(
            source_title="Travel Permit and Payment FAQ",
            section="Sales Notes",
        ),
        make_eval_case(),
    )

    assert detail.relevance_grade == 0
    assert detail.judged is True
    assert detail.relevant_match is False
    assert detail.direct_match is False
    assert detail.source_match is False
    assert detail.covers_facets == ()


def test_has_expected_match_and_source_check_the_top_k_window() -> None:
    eval_case = make_eval_case()
    unjudged_same_source = make_retrieved_chunk(section="Departure Notes", rank=1)
    direct_result = make_retrieved_chunk(section="Suitable For", rank=2)
    results = [unjudged_same_source, direct_result]

    assert has_expected_source(results, eval_case, top_k=1) is True
    assert has_expected_match(results, eval_case, top_k=1) is False
    assert has_expected_match(results, eval_case, top_k=2) is True


def test_reciprocal_rank_uses_first_direct_answer() -> None:
    results = [
        make_retrieved_chunk(section="Key Experiences", rank=1),
        make_retrieved_chunk(section="Suitable For", rank=2),
    ]

    assert reciprocal_rank(results, make_eval_case()) == 0.5


def test_ndcg_rewards_better_graded_ordering() -> None:
    eval_case = make_eval_case()
    direct_first = [
        make_retrieved_chunk(section="Suitable For", rank=1),
        make_retrieved_chunk(section="Pricing Notes", rank=2),
        make_retrieved_chunk(section="Key Experiences", rank=3),
    ]
    support_first = [
        make_retrieved_chunk(section="Key Experiences", rank=1),
        make_retrieved_chunk(section="Suitable For", rank=2),
        make_retrieved_chunk(section="Departure Notes", rank=3),
    ]

    assert ndcg_at_k(direct_first, eval_case, top_k=3) == pytest.approx(1.0)
    assert ndcg_at_k(support_first, eval_case, top_k=3) < 1.0


def test_facet_recall_counts_only_facets_covered_by_direct_answers() -> None:
    family_only = [make_retrieved_chunk(section="Suitable For")]
    both_facets = [
        make_retrieved_chunk(section="Suitable For", rank=1),
        make_retrieved_chunk(section="Pricing Notes", rank=2),
    ]

    assert facet_recall_at_k(family_only, make_eval_case(), top_k=3) == 0.5
    assert facet_recall_at_k(both_facets, make_eval_case(), top_k=3) == 1.0


def test_unjudged_rate_reports_label_pool_gaps() -> None:
    results = [
        make_retrieved_chunk(section="Suitable For", rank=1),
        make_retrieved_chunk(section="Departure Notes", rank=2),
    ]

    assert unjudged_rate_at_k(results, make_eval_case(), top_k=3) == 0.5


def test_invalid_top_k_is_rejected() -> None:
    with pytest.raises(ValueError):
        has_expected_match([make_retrieved_chunk()], make_eval_case(), top_k=0)


def test_eval_judgments_must_exist_in_the_knowledge_snapshot() -> None:
    eval_case = make_eval_case()
    chunks = [
        make_knowledge_chunk(judgment.source_title, judgment.section, index)
        for index, judgment in enumerate(eval_case.judgments)
    ]

    validate_eval_cases_against_chunks([eval_case], chunks)

    with pytest.raises(ValueError, match="Pricing Notes"):
        validate_eval_cases_against_chunks([eval_case], chunks[:1])
