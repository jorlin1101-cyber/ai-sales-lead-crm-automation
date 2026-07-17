import pytest

from lead_cleaner.rag.dense_retriever import build_dense_search_text, cosine_similarity, build_dense_index, retrieve_dense
from lead_cleaner.rag.schemas import KnowledgeChunk


def make_chunk(
    chunk_id: str = "chunk_001",
    source_title: str = "Tibet Cultural Tour",
    section: str = "Key Experiences",
    text: str = "Visit monasteries with a local guide.",
    doc_type: str = "product",
    region: str = "tibet",
    product_name: str | None = "Tibet Cultural Tour",
) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        source_type="notion_page",
        notion_page_id="page_001",
        source_title=source_title,
        source_path="AI Sales Knowledge Base/Products/Tibet/Tibet Cultural Tour",
        doc_type=doc_type,
        region=region,
        product_name=product_name,
        section=section,
        chunk_index=0,
        chunk_strategy="heading_section",
        text=text,
        last_edited_time="2026-01-01T00:00:00Z",
    )


class FakeEmbeddingProvider:
    model_name = "fake-embedding-model"

    def embed_text(self, text: str) -> list[float]:
        if "Yunnan" in text:
            return [0.0, 1.0, 0.0]

        return [1.0, 0.0, 0.0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


def test_build_dense_search_text_includes_metadata_and_content() -> None:
    chunk = make_chunk()

    search_text = build_dense_search_text(chunk)

    assert "Title: Tibet Cultural Tour" in search_text
    assert "Section: Key Experiences" in search_text
    assert "Document type: product" in search_text
    assert "Region: tibet" in search_text
    assert "Product: Tibet Cultural Tour" in search_text
    assert "Content:" in search_text
    assert "Visit monasteries with a local guide." in search_text


def test_cosine_similarity_returns_one_for_same_direction() -> None:
    score = cosine_similarity([1.0, 1.0], [2.0, 2.0])

    assert score == pytest.approx(1.0)


def test_cosine_similarity_returns_zero_for_zero_vector() -> None:
    score = cosine_similarity([0.0, 0.0], [1.0, 1.0])

    assert score == 0.0


def test_cosine_similarity_rejects_empty_vectors() -> None:
    try:
        cosine_similarity([], [1.0, 1.0])
    except ValueError as error:
        assert "must not be empty" in str(error)
    else:
        raise AssertionError("Expected ValueError for empty vector.")


def test_cosine_similarity_rejects_dimension_mismatch() -> None:
    try:
        cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0])
    except ValueError as error:
        assert "same dimension" in str(error)
    else:
        raise AssertionError("Expected ValueError for dimension mismatch.")


def test_build_dense_index_creates_index_with_vectors_and_metadata() -> None:
    chunks = [
        make_chunk(chunk_id="chunk_tibet", source_title="Tibet Cultural Tour"),
        make_chunk(
            chunk_id="chunk_yunnan",
            source_title="Yunnan Family Tour",
            region="yunnan",
            product_name="Yunnan Family Tour",
        ),
    ]
    provider = FakeEmbeddingProvider()

    index = build_dense_index(
        chunks=chunks,
        embedding_provider=provider,
    )

    assert index.chunks == chunks
    assert index.vectors == [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    assert index.embedding_model == "fake-embedding-model"
    assert index.vector_dimension == 3


def test_build_dense_index_rejects_empty_chunks() -> None:
    provider = FakeEmbeddingProvider()

    try:
        build_dense_index(chunks=[], embedding_provider=provider)
    except ValueError as error:
        assert "Chunks must not be empty" in str(error)
    else:
        raise AssertionError("Expected ValueError for empty chunks.")


class WrongCountEmbeddingProvider:
    model_name = "wrong-count-model"

    def embed_text(self, text: str) -> list[float]:
        return [1.0, 0.0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0]]


def test_build_dense_index_rejects_vector_count_mismatch() -> None:
    chunks = [
        make_chunk(chunk_id="chunk_1"),
        make_chunk(chunk_id="chunk_2"),
    ]

    try:
        build_dense_index(
            chunks=chunks,
            embedding_provider=WrongCountEmbeddingProvider(),
        )
    except ValueError as error:
        assert "Number of vectors must match number of chunks" in str(error)
    else:
        raise AssertionError("Expected ValueError for vector count mismatch.")


class WrongDimensionEmbeddingProvider:
    model_name = "wrong-dimension-model"

    def embed_text(self, text: str) -> list[float]:
        return [1.0, 0.0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [
            [1.0, 0.0],
            [1.0, 0.0, 0.0],
        ]


def test_build_dense_index_rejects_vector_dimension_mismatch() -> None:
    chunks = [
        make_chunk(chunk_id="chunk_1"),
        make_chunk(chunk_id="chunk_2"),
    ]

    try:
        build_dense_index(
            chunks=chunks,
            embedding_provider=WrongDimensionEmbeddingProvider(),
        )
    except ValueError as error:
        assert "same dimension" in str(error)
    else:
        raise AssertionError("Expected ValueError for vector dimension mismatch.")


def test_retrieve_dense_returns_ranked_retrieved_chunks() -> None:
    chunks = [
        make_chunk(
            chunk_id="chunk_tibet",
            source_title="Tibet Cultural Tour",
            region="tibet",
            product_name="Tibet Cultural Tour",
        ),
        make_chunk(
            chunk_id="chunk_yunnan",
            source_title="Yunnan Family Tour",
            region="yunnan",
            product_name="Yunnan Family Tour",
        ),
    ]
    provider = FakeEmbeddingProvider()
    index = build_dense_index(chunks=chunks, embedding_provider=provider)

    results = retrieve_dense(
        query="Yunnan family travel",
        index=index,
        embedding_provider=provider,
        top_k=1,
    )

    assert len(results) == 1
    assert results[0].chunk_id == "chunk_yunnan"
    assert results[0].rank == 1
    assert results[0].retrieval_source == "dense"
    assert results[0].source_title == "Yunnan Family Tour"
    assert results[0].region == "yunnan"
    assert results[0].score == pytest.approx(1.0)


def test_retrieve_dense_returns_empty_list_for_blank_query() -> None:
    chunks = [make_chunk()]
    provider = FakeEmbeddingProvider()
    index = build_dense_index(chunks=chunks, embedding_provider=provider)

    results = retrieve_dense(
        query="   ",
        index=index,
        embedding_provider=provider,
        top_k=5,
    )

    assert results == []


def test_retrieve_dense_rejects_invalid_top_k() -> None:
    chunks = [make_chunk()]
    provider = FakeEmbeddingProvider()
    index = build_dense_index(chunks=chunks, embedding_provider=provider)

    try:
        retrieve_dense(
            query="Tibet cultural tour",
            index=index,
            embedding_provider=provider,
            top_k=0,
        )
    except ValueError as error:
        assert "top_k must be greater than 0" in str(error)
    else:
        raise AssertionError("Expected ValueError for invalid top_k.")


class DifferentModelEmbeddingProvider(FakeEmbeddingProvider):
    model_name = "different-model"

def test_retrieve_dense_rejects_embedding_model_mismatch() -> None:
    chunks = [make_chunk()]
    provider = FakeEmbeddingProvider()
    index = build_dense_index(chunks=chunks, embedding_provider=provider)

    try:
        retrieve_dense(
            query="Tibet cultural tour",
            index=index,
            embedding_provider=DifferentModelEmbeddingProvider(),
            top_k=5,
        )
    except ValueError as error:
        assert "Embedding provider model must match index embedding model" in str(error)
    else:
        raise AssertionError("Expected ValueError for embedding model mismatch.")
