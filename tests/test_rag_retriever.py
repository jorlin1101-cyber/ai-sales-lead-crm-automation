from typing import cast

import pytest

from lead_cleaner.rag import retriever as retriever_module
from lead_cleaner.rag.bm25_retriever import BM25Index
from lead_cleaner.rag.dense_retriever import DenseIndex
from lead_cleaner.rag.retriever import (
    DisabledRagRetriever,
    HybridRagRetriever,
    RagRetrievalOutcome,
    RagUnavailableError,
    UnavailableRagRetriever,
)
from lead_cleaner.rag.schemas import RetrievedChunk


class FakeEmbeddingProvider:
    model_name = "fake-model"

    def __init__(self) -> None:
        self.close_calls = 0

    def embed_text(self, text: str) -> list[float]:
        return [1.0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] for _ in texts]

    def close(self) -> None:
        self.close_calls += 1


def make_retrieved_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="chunk-1",
        source_type="notion_page",
        notion_page_id="private-page-id",
        source_title="Pricing Rules",
        source_path="Knowledge/Pricing Rules",
        doc_type="pricing",
        region="general",
        product_name=None,
        section="Pricing Variables",
        text="Internal chunk text",
        score=1.0,
        rank=1,
        retrieval_source="fusion",
    )


def make_hybrid_retriever(*, required: bool) -> tuple[HybridRagRetriever, FakeEmbeddingProvider]:
    provider = FakeEmbeddingProvider()
    retriever = HybridRagRetriever(
        bm25_index=cast(BM25Index, object()),
        dense_index=cast(DenseIndex, object()),
        embedding_provider=provider,
        retrieval_method="keyword_rrf",
        required=required,
    )
    return retriever, provider


def test_disabled_and_unavailable_retrievers_report_truthful_methods() -> None:
    disabled = DisabledRagRetriever().retrieve("query")
    unavailable = UnavailableRagRetriever().retrieve("query")

    assert disabled.retrieval_method == "disabled"
    assert disabled.chunks == []
    assert unavailable.retrieval_method == "unavailable"
    assert unavailable.failure_reason == "startup_failure"


def test_hybrid_retriever_returns_ranked_chunks(monkeypatch) -> None:
    retriever, _provider = make_hybrid_retriever(required=False)
    monkeypatch.setattr(
        retriever_module,
        "retrieve_hybrid",
        lambda **kwargs: [make_retrieved_chunk()],
    )

    outcome = retriever.retrieve("pricing query")

    assert outcome.retrieval_method == "keyword_rrf"
    assert [chunk.chunk_id for chunk in outcome.chunks] == ["chunk-1"]


def test_optional_runtime_failure_becomes_unavailable(monkeypatch) -> None:
    retriever, _provider = make_hybrid_retriever(required=False)
    monkeypatch.setattr(
        retriever_module,
        "retrieve_hybrid",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("private failure")),
    )

    outcome = retriever.retrieve("pricing query")

    assert outcome.retrieval_method == "unavailable"
    assert outcome.failure_reason == "retrieval_failure"
    assert outcome.chunks == []


def test_required_runtime_failure_raises_safe_error(monkeypatch) -> None:
    retriever, _provider = make_hybrid_retriever(required=True)
    monkeypatch.setattr(
        retriever_module,
        "retrieve_hybrid",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("private failure")),
    )

    with pytest.raises(RagUnavailableError, match="Required RAG retrieval failed"):
        retriever.retrieve("pricing query")


def test_hybrid_retriever_closes_embedding_provider() -> None:
    retriever, provider = make_hybrid_retriever(required=False)

    retriever.close()

    assert provider.close_calls == 1


def test_unavailable_outcome_requires_failure_reason() -> None:
    with pytest.raises(ValueError, match="requires a failure_reason"):
        RagRetrievalOutcome(retrieval_method="unavailable")
