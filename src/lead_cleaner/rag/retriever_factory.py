from pathlib import Path

import httpx
from pydantic import ValidationError

from lead_cleaner.config import RagBackend, Settings
from lead_cleaner.rag.bge_embedding_provider import BgeM3EmbeddingProvider
from lead_cleaner.rag.bm25_retriever import build_bm25_index
from lead_cleaner.rag.demo_embedding_provider import KeywordEmbeddingProvider
from lead_cleaner.rag.dense_retriever import EmbeddingProvider, build_dense_index
from lead_cleaner.rag.knowledge_loader import load_knowledge_chunks
from lead_cleaner.rag.retriever import (
    CloseableEmbeddingProvider,
    DisabledRagRetriever,
    HybridRagRetriever,
    RagRetriever,
    RagUnavailableError,
    SuccessfulRetrievalMethod,
    UnavailableRagRetriever,
)


def create_rag_retriever(settings: Settings) -> RagRetriever:
    """Build one reusable retriever from validated application settings."""

    if settings.rag_backend == RagBackend.DISABLED:
        return DisabledRagRetriever()

    embedding_provider: EmbeddingProvider
    retrieval_method: SuccessfulRetrievalMethod

    if settings.rag_backend == RagBackend.KEYWORD_RRF:
        embedding_provider = KeywordEmbeddingProvider()
        retrieval_method = "keyword_rrf"
    elif settings.rag_backend == RagBackend.BGE_RRF:
        embedding_provider = BgeM3EmbeddingProvider(
            base_url=settings.bge_api_base_url,
            model_name=settings.bge_embedding_model,
            timeout=settings.bge_timeout_seconds,
        )
        retrieval_method = "bge_rrf"
    else:
        raise RagUnavailableError(f"Unsupported RAG_BACKEND: {settings.rag_backend}")

    try:
        chunks = load_knowledge_chunks(Path(settings.knowledge_chunks_path))
        bm25_index = build_bm25_index(chunks)
        dense_index = build_dense_index(
            chunks=chunks,
            embedding_provider=embedding_provider,
        )
    except (
        OSError,
        ValidationError,
        ValueError,
        RuntimeError,
        httpx.HTTPError,
    ) as error:
        if isinstance(embedding_provider, CloseableEmbeddingProvider):
            embedding_provider.close()

        if settings.rag_required:
            raise RagUnavailableError("Required RAG backend failed to start.") from error

        return UnavailableRagRetriever(failure_reason="startup_failure")

    return HybridRagRetriever(
        bm25_index=bm25_index,
        dense_index=dense_index,
        embedding_provider=embedding_provider,
        retrieval_method=retrieval_method,
        required=settings.rag_required,
        top_k=settings.rag_top_k,
        candidate_top_k=settings.rag_candidate_top_k,
    )
