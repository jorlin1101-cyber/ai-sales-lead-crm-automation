import math

from dataclasses import dataclass
from typing import Protocol

from lead_cleaner.rag.schemas import KnowledgeChunk, RetrievedChunk


class EmbeddingProvider(Protocol):
    """Interface for converting text into embedding vectors."""

    model_name: str

    def embed_text(self, text: str) -> list[float]: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class DenseIndex:
    """In-memory dense retrieval index for knowledge chunks."""

    chunks: list[KnowledgeChunk]
    vectors: list[list[float]]
    embedding_model: str
    vector_dimension: int


def build_dense_search_text(chunk: KnowledgeChunk) -> str:
    parts = [
        f"Title: {chunk.source_title}",
        f"Section: {chunk.section}",
        f"Document type: {chunk.doc_type}",
        f"Region: {chunk.region}",
    ]

    if chunk.product_name:
        parts.append(f"Product: {chunk.product_name}")

    parts.append("Content:")
    parts.append(chunk.text)

    return "\n".join(parts)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        raise ValueError("Vectors must not be empty.")

    if len(a) != len(b):
        raise ValueError("Vectors must have the same dimension.")

    dot_product = sum(left * right for left, right in zip(a, b))
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def build_dense_index(
    chunks: list[KnowledgeChunk],
    embedding_provider: EmbeddingProvider,
) -> DenseIndex:
    if not chunks:
        raise ValueError("Chunks must not be empty.")

    search_texts = [build_dense_search_text(chunk) for chunk in chunks]
    vectors = embedding_provider.embed_texts(search_texts)

    if len(vectors) != len(chunks):
        raise ValueError("Number of vectors must match number of chunks.")

    first_vector = vectors[0]

    if not first_vector:
        raise ValueError("Embedding vectors must not be empty.")

    vector_dimension = len(first_vector)

    for vector in vectors:
        if not vector:
            raise ValueError("Embedding vectors must not be empty.")

        if len(vector) != vector_dimension:
            raise ValueError("All embedding vectors must have the same dimension.")

    return DenseIndex(
        chunks=chunks,
        vectors=vectors,
        embedding_model=embedding_provider.model_name,
        vector_dimension=vector_dimension,
    )


def knowledge_chunk_to_dense_retrieved_chunk(
    chunk: KnowledgeChunk,
    score: float,
    rank: int,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.chunk_id,
        source_type=chunk.source_type,
        notion_page_id=chunk.notion_page_id,
        source_title=chunk.source_title,
        source_path=chunk.source_path,
        doc_type=chunk.doc_type,
        region=chunk.region,
        product_name=chunk.product_name,
        section=chunk.section,
        text=chunk.text,
        score=score,
        rank=rank,
        retrieval_source="dense",
    )


def retrieve_dense(
    query: str,
    index: DenseIndex,
    embedding_provider: EmbeddingProvider,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")

    if not query.strip():
        return []

    if embedding_provider.model_name != index.embedding_model:
        raise ValueError("Embedding provider model must match index embedding model.")

    query_vector = embedding_provider.embed_text(query)

    if not query_vector:
        raise ValueError("Query vector must not be empty.")

    if len(query_vector) != index.vector_dimension:
        raise ValueError("Query vector dimension must match index vector dimension.")

    scored_chunks: list[tuple[KnowledgeChunk, float]] = []

    for chunk, chunk_vector in zip(index.chunks, index.vectors):
        score = cosine_similarity(query_vector, chunk_vector)

        if score > 0:
            scored_chunks.append((chunk, score))

    scored_chunks.sort(key=lambda item: (-item[1], item[0].chunk_id))

    top_results = scored_chunks[:top_k]

    return [
        knowledge_chunk_to_dense_retrieved_chunk(
            chunk=chunk,
            score=score,
            rank=rank,
        )
        for rank, (chunk, score) in enumerate(top_results, start=1)
    ]
