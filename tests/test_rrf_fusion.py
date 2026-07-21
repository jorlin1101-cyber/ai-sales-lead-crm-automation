import pytest

from lead_cleaner.rag.rrf_fusion import DEFAULT_RRF_K, rrf_score, fuse_retrieved_chunks
from lead_cleaner.rag.schemas import RetrievedChunk


def test_rrf_score_gives_higher_score_to_better_rank() -> None:
    rank_1_score = rrf_score(rank=1)
    rank_3_score = rrf_score(rank=3)

    assert rank_1_score > rank_3_score


def test_rrf_score_uses_default_k() -> None:
    score = rrf_score(rank=1)

    assert score == pytest.approx(1 / (DEFAULT_RRF_K + 1))


def test_rrf_score_rejects_invalid_rank() -> None:
    try:
        rrf_score(rank=0)
    except ValueError as error:
        assert "rank must be greater than 0" in str(error)
    else:
        raise AssertionError("Expected ValueError for invalid rank.")


def make_retrieved_chunk(
    chunk_id: str,
    rank: int,
    retrieval_source: str = "bm25",
    source_title: str | None = None,
) -> RetrievedChunk:
    title = source_title or chunk_id

    return RetrievedChunk(
        chunk_id=chunk_id,
        source_type="notion_page",
        notion_page_id=f"page_{chunk_id}",
        source_title=title,
        source_path=f"AI Sales Knowledge Base/{title}",
        doc_type="product",
        region="tibet",
        product_name=title,
        section="Overview",
        text=f"Content for {title}",
        score=1.0,
        rank=rank,
        retrieval_source=retrieval_source,
    )


def test_fuse_retrieved_chunks_boosts_chunks_found_by_multiple_retrievers() -> None:
    bm25_results = [
        make_retrieved_chunk("chunk_a", rank=1, retrieval_source="bm25"),
        make_retrieved_chunk("chunk_b", rank=2, retrieval_source="bm25"),
    ]
    dense_results = [
        make_retrieved_chunk("chunk_b", rank=1, retrieval_source="dense"),
        make_retrieved_chunk("chunk_c", rank=2, retrieval_source="dense"),
    ]

    results = fuse_retrieved_chunks(
        result_lists=[bm25_results, dense_results],
        top_k=3,
    )

    assert [result.chunk_id for result in results] == [
        "chunk_b",
        "chunk_a",
        "chunk_c",
    ]
    assert results[0].retrieval_source == "fusion"
    assert results[0].rank == 1
    assert results[0].score == pytest.approx(rrf_score(rank=2) + rrf_score(rank=1))


def test_fuse_retrieved_chunks_respects_top_k() -> None:
    bm25_results = [
        make_retrieved_chunk("chunk_a", rank=1),
        make_retrieved_chunk("chunk_b", rank=2),
    ]
    dense_results = [
        make_retrieved_chunk("chunk_c", rank=1, retrieval_source="dense"),
    ]

    results = fuse_retrieved_chunks(
        result_lists=[bm25_results, dense_results],
        top_k=2,
    )

    assert len(results) == 2


def test_fuse_retrieved_chunks_returns_empty_list_for_empty_results() -> None:
    results = fuse_retrieved_chunks(result_lists=[], top_k=5)

    assert results == []


def test_fuse_retrieved_chunks_rejects_invalid_top_k() -> None:
    try:
        fuse_retrieved_chunks(result_lists=[], top_k=0)
    except ValueError as error:
        assert "top_k must be greater than 0" in str(error)
    else:
        raise AssertionError("Expected ValueError for invalid top_k.")
