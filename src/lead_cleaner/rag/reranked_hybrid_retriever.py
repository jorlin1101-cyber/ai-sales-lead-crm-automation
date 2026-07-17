from typing import Protocol

from lead_cleaner.rag.bm25_retriever import BM25Index
from lead_cleaner.rag.dense_retriever import DenseIndex, EmbeddingProvider
from lead_cleaner.rag.hybrid_retriever import retrieve_hybrid
from lead_cleaner.rag.rrf_fusion import DEFAULT_RRF_K
from lead_cleaner.rag.schemas import RetrievedChunk


class Reranker(Protocol):
    """Interface for reranking retrieved candidate chunks."""

    def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int = 5,
    ) -> list[RetrievedChunk]: ...


def retrieve_reranked_hybrid(
    query: str,
    bm25_index: BM25Index,
    dense_index: DenseIndex,
    embedding_provider: EmbeddingProvider,
    reranker: Reranker,
    top_k: int = 3,
    rrf_candidate_top_k: int = 20,
    rerank_candidate_top_k: int = 10,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[RetrievedChunk]:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")

    if rerank_candidate_top_k < top_k:
        raise ValueError("rerank_candidate_top_k must be greater than or equal to top_k.")

    if rrf_candidate_top_k < rerank_candidate_top_k:
        raise ValueError(
            "rrf_candidate_top_k must be greater than or equal to rerank_candidate_top_k."
        )

    if not query.strip():
        return []

    fusion_candidates = retrieve_hybrid(
        query=query,
        bm25_index=bm25_index,
        dense_index=dense_index,
        embedding_provider=embedding_provider,
        top_k=rerank_candidate_top_k,
        candidate_top_k=rrf_candidate_top_k,
        rrf_k=rrf_k,
    )

    return reranker.rerank(
        query=query,
        candidates=fusion_candidates,
        top_k=top_k,
    )
