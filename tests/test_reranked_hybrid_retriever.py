import pytest

from lead_cleaner.rag.bm25_retriever import BM25Index, build_bm25_index
from lead_cleaner.rag.demo_embedding_provider import KeywordEmbeddingProvider
from lead_cleaner.rag.dense_retriever import DenseIndex, build_dense_index
from lead_cleaner.rag.reranked_hybrid_retriever import retrieve_reranked_hybrid
from lead_cleaner.rag.schemas import KnowledgeChunk, RetrievedChunk


def make_chunk(
    chunk_id: str,
    source_title: str,
    section: str,
    text: str,
    chunk_index: int,
) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        source_type="notion_page",
        notion_page_id=f"page_{chunk_id}",
        source_title=source_title,
        source_path=f"Knowledge / {source_title}",
        doc_type="product",
        region="tibet",
        product_name=source_title,
        section=section,
        chunk_index=chunk_index,
        chunk_strategy="heading_section",
        text=text,
        last_edited_time="2026-06-30T00:00:00.000Z",
    )


class FakeReranker:
    def __init__(self) -> None:
        self.received_query: str | None = None
        self.received_candidates: list[RetrievedChunk] = []
        self.received_top_k: int | None = None

    def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        self.received_query = query
        self.received_candidates = candidates
        self.received_top_k = top_k

        selected_candidates = sorted(
            candidates,
            key=lambda candidate: candidate.chunk_id,
            reverse=True,
        )[:top_k]

        return [
            RetrievedChunk(
                chunk_id=candidate.chunk_id,
                source_type=candidate.source_type,
                notion_page_id=candidate.notion_page_id,
                source_title=candidate.source_title,
                source_path=candidate.source_path,
                doc_type=candidate.doc_type,
                region=candidate.region,
                product_name=candidate.product_name,
                section=candidate.section,
                text=candidate.text,
                score=1.0 / rank,
                rank=rank,
                retrieval_source="rerank",
            )
            for rank, candidate in enumerate(selected_candidates, start=1)
        ]


def build_test_indexes() -> tuple[BM25Index, DenseIndex, KeywordEmbeddingProvider]:
    chunks = [
        make_chunk(
            chunk_id="chunk_a",
            source_title="Tibet Cultural Tour",
            section="Suitable For",
            text="Suitable for travelers seeking a deeper Tibetan cultural journey.",
            chunk_index=0,
        ),
        make_chunk(
            chunk_id="chunk_b",
            source_title="Tibet Cultural Tour",
            section="Pricing Notes",
            text="Pricing depends on hotel level, season, and guide arrangement.",
            chunk_index=1,
        ),
        make_chunk(
            chunk_id="chunk_c",
            source_title="Tibet Cultural Tour",
            section="Key Experiences",
            text="Includes monasteries, Tibetan family visits, and cultural exchange.",
            chunk_index=2,
        ),
    ]

    embedding_provider = KeywordEmbeddingProvider()
    bm25_index = build_bm25_index(chunks)
    dense_index = build_dense_index(
        chunks=chunks,
        embedding_provider=embedding_provider,
    )

    return bm25_index, dense_index, embedding_provider


def test_retrieve_reranked_hybrid_passes_fusion_candidates_to_reranker() -> None:
    bm25_index, dense_index, embedding_provider = build_test_indexes()
    reranker = FakeReranker()

    results = retrieve_reranked_hybrid(
        query="deeper Tibetan cultural journey",
        bm25_index=bm25_index,
        dense_index=dense_index,
        embedding_provider=embedding_provider,
        reranker=reranker,
        top_k=2,
        rrf_candidate_top_k=3,
        rerank_candidate_top_k=3,
    )

    assert reranker.received_query == "deeper Tibetan cultural journey"
    assert reranker.received_top_k == 2
    assert len(reranker.received_candidates) == 3
    assert all(candidate.retrieval_source == "fusion" for candidate in reranker.received_candidates)

    assert len(results) == 2
    assert all(result.retrieval_source == "rerank" for result in results)
    assert [result.rank for result in results] == [1, 2]


def test_retrieve_reranked_hybrid_returns_empty_for_blank_query() -> None:
    bm25_index, dense_index, embedding_provider = build_test_indexes()
    reranker = FakeReranker()

    results = retrieve_reranked_hybrid(
        query="   ",
        bm25_index=bm25_index,
        dense_index=dense_index,
        embedding_provider=embedding_provider,
        reranker=reranker,
        top_k=2,
    )

    assert results == []
    assert reranker.received_candidates == []


def test_retrieve_reranked_hybrid_raises_for_invalid_top_k() -> None:
    bm25_index, dense_index, embedding_provider = build_test_indexes()
    reranker = FakeReranker()

    with pytest.raises(ValueError):
        retrieve_reranked_hybrid(
            query="hello",
            bm25_index=bm25_index,
            dense_index=dense_index,
            embedding_provider=embedding_provider,
            reranker=reranker,
            top_k=0,
        )


def test_retrieve_reranked_hybrid_raises_when_rerank_candidates_less_than_top_k() -> None:
    bm25_index, dense_index, embedding_provider = build_test_indexes()
    reranker = FakeReranker()

    with pytest.raises(ValueError):
        retrieve_reranked_hybrid(
            query="hello",
            bm25_index=bm25_index,
            dense_index=dense_index,
            embedding_provider=embedding_provider,
            reranker=reranker,
            top_k=5,
            rerank_candidate_top_k=3,
        )


def test_retrieve_reranked_hybrid_raises_when_rrf_candidates_less_than_rerank_candidates() -> None:
    bm25_index, dense_index, embedding_provider = build_test_indexes()
    reranker = FakeReranker()

    with pytest.raises(ValueError):
        retrieve_reranked_hybrid(
            query="hello",
            bm25_index=bm25_index,
            dense_index=dense_index,
            embedding_provider=embedding_provider,
            reranker=reranker,
            top_k=3,
            rrf_candidate_top_k=5,
            rerank_candidate_top_k=10,
        )
