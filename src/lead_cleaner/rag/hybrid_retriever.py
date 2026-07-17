from lead_cleaner.rag.bm25_retriever import BM25Index, retrieve_bm25
from lead_cleaner.rag.dense_retriever import (
    DenseIndex,
    EmbeddingProvider,
    retrieve_dense,
)
from lead_cleaner.rag.rrf_fusion import DEFAULT_RRF_K, fuse_retrieved_chunks
from lead_cleaner.rag.schemas import RetrievedChunk


def retrieve_hybrid(
    query: str,
    bm25_index: BM25Index,
    dense_index: DenseIndex,
    embedding_provider: EmbeddingProvider,
    top_k: int = 5,
    candidate_top_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[RetrievedChunk]:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")

    if candidate_top_k is None:
        candidate_top_k = top_k

    if candidate_top_k < top_k:
        raise ValueError("candidate_top_k must be greater than or equal to top_k.")

    if not query.strip():
        return []

    bm25_results = retrieve_bm25(
        query=query,
        index=bm25_index,
        top_k=candidate_top_k,
    )

    dense_results = retrieve_dense(
        query=query,
        index=dense_index,
        embedding_provider=embedding_provider,
        top_k=candidate_top_k,
    )

    return fuse_retrieved_chunks(
        result_lists=[bm25_results, dense_results],
        top_k=top_k,
        k=rrf_k,
    )
