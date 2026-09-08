from typing import Literal, Protocol, Self, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from lead_cleaner.rag.bm25_retriever import BM25Index
from lead_cleaner.rag.dense_retriever import DenseIndex, EmbeddingProvider
from lead_cleaner.rag.hybrid_retriever import retrieve_hybrid
from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.ai_output import RetrievalMethod


RagFailureReason = Literal["startup_failure", "retrieval_failure"]
SuccessfulRetrievalMethod = Literal["keyword_rrf", "bge_rrf"]


class RagUnavailableError(Exception):
    """Raised when a required RAG backend cannot serve a request."""

    error_code = "rag_unavailable"


class RagRetrievalOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunks: list[RetrievedChunk] = Field(default_factory=list, max_length=3)
    retrieval_method: RetrievalMethod
    failure_reason: RagFailureReason | None = None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.retrieval_method == "unavailable" and self.failure_reason is None:
            raise ValueError("unavailable retrieval requires a failure_reason")

        if self.retrieval_method != "unavailable" and self.failure_reason is not None:
            raise ValueError("failure_reason is only valid for unavailable retrieval")

        if self.retrieval_method in {"disabled", "unavailable", "skipped"} and self.chunks:
            raise ValueError("disabled, unavailable, and skipped retrieval cannot contain chunks")

        return self


@runtime_checkable
class RagRetriever(Protocol):
    def retrieve(self, query: str) -> RagRetrievalOutcome:
        """Return up to three ranked knowledge chunks."""
        ...


@runtime_checkable
class CloseableRagRetriever(RagRetriever, Protocol):
    def close(self) -> None:
        """Release resources owned by the retriever."""
        ...


@runtime_checkable
class ProductManualRetriever(RagRetriever, Protocol):
    def product_manuals(self, region: str) -> list[RetrievedChunk]:
        """Read product sections from the same configured knowledge snapshot."""
        ...


@runtime_checkable
class CloseableEmbeddingProvider(EmbeddingProvider, Protocol):
    def close(self) -> None:
        """Release resources owned by the embedding provider."""
        ...


class DisabledRagRetriever:
    def retrieve(self, query: str) -> RagRetrievalOutcome:
        return RagRetrievalOutcome(retrieval_method="disabled")


class UnavailableRagRetriever:
    def __init__(self, *, failure_reason: RagFailureReason = "startup_failure") -> None:
        self._failure_reason = failure_reason

    def retrieve(self, query: str) -> RagRetrievalOutcome:
        return RagRetrievalOutcome(
            retrieval_method="unavailable",
            failure_reason=self._failure_reason,
        )


class HybridRagRetriever:
    def __init__(
        self,
        *,
        bm25_index: BM25Index,
        dense_index: DenseIndex,
        embedding_provider: EmbeddingProvider,
        retrieval_method: SuccessfulRetrievalMethod,
        required: bool,
        top_k: int = 3,
        candidate_top_k: int = 5,
    ) -> None:
        self._bm25_index = bm25_index
        self._dense_index = dense_index
        self._embedding_provider = embedding_provider
        self._retrieval_method = retrieval_method
        self._required = required
        self._top_k = top_k
        self._candidate_top_k = candidate_top_k

    def retrieve(self, query: str) -> RagRetrievalOutcome:
        try:
            chunks = retrieve_hybrid(
                query=query,
                bm25_index=self._bm25_index,
                dense_index=self._dense_index,
                embedding_provider=self._embedding_provider,
                top_k=self._top_k,
                candidate_top_k=self._candidate_top_k,
            )
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            if self._required:
                raise RagUnavailableError("Required RAG retrieval failed.") from error

            return RagRetrievalOutcome(
                retrieval_method="unavailable",
                failure_reason="retrieval_failure",
            )

        return RagRetrievalOutcome(
            chunks=chunks,
            retrieval_method=self._retrieval_method,
        )

    def product_manuals(self, region: str) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(
                **chunk.model_dump(
                    include={
                        "chunk_id",
                        "source_type",
                        "notion_page_id",
                        "source_title",
                        "source_path",
                        "doc_type",
                        "region",
                        "product_name",
                        "section",
                        "text",
                    }
                ),
                score=1.0,
                rank=index + 1,
                retrieval_source="bm25",
            )
            for index, chunk in enumerate(self._bm25_index.chunks)
            if chunk.doc_type == "product" and chunk.region == region and chunk.product_name
        ]

    def close(self) -> None:
        if isinstance(self._embedding_provider, CloseableEmbeddingProvider):
            self._embedding_provider.close()
