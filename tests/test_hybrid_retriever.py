from lead_cleaner.rag.bm25_retriever import build_bm25_index
from lead_cleaner.rag.dense_retriever import build_dense_index
from lead_cleaner.rag.hybrid_retriever import retrieve_hybrid
from lead_cleaner.rag.schemas import KnowledgeChunk


class FakeEmbeddingProvider:
    model_name = "fake-embedding-model"

    def embed_text(self, text: str) -> list[float]:
        normalized_text = text.lower()

        if "yunnan" in normalized_text or "family" in normalized_text:
            return [0.0, 1.0, 0.0]

        if "tibet" in normalized_text or "cultural" in normalized_text:
            return [1.0, 0.0, 0.0]

        return [0.0, 0.0, 1.0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


def make_chunk(
    chunk_id: str,
    source_title: str,
    text: str,
    region: str,
    product_name: str | None = None,
) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        source_type="notion_page",
        notion_page_id=f"page_{chunk_id}",
        source_title=source_title,
        source_path=f"AI Sales Knowledge Base/Products/{source_title}",
        doc_type="product",
        region=region,
        product_name=product_name,
        section="Overview",
        chunk_index=0,
        chunk_strategy="heading_section",
        text=text,
        last_edited_time="2026-01-01T00:00:00Z",
    )


def build_test_indexes() -> tuple:
    chunks = [
        make_chunk(
            chunk_id="chunk_tibet",
            source_title="Tibet Cultural Tour",
            text="Tibet cultural tour with monastery visits and local family experience.",
            region="tibet",
            product_name="Tibet Cultural Tour",
        ),
        make_chunk(
            chunk_id="chunk_yunnan",
            source_title="Yunnan Family Tour",
            text="Yunnan family travel with cultural experiences.",
            region="yunnan",
            product_name="Yunnan Family Tour",
        ),
    ]
    provider = FakeEmbeddingProvider()

    bm25_index = build_bm25_index(chunks)
    dense_index = build_dense_index(
        chunks=chunks,
        embedding_provider=provider,
    )

    return bm25_index, dense_index, provider


def test_retrieve_hybrid_returns_fusion_results() -> None:
    bm25_index, dense_index, provider = build_test_indexes()

    results = retrieve_hybrid(
        query="Tibet cultural tour",
        bm25_index=bm25_index,
        dense_index=dense_index,
        embedding_provider=provider,
        top_k=1,
    )

    assert len(results) == 1
    assert results[0].chunk_id == "chunk_tibet"
    assert results[0].retrieval_source == "fusion"
    assert results[0].rank == 1
    assert results[0].score > 0


def test_retrieve_hybrid_returns_empty_list_for_blank_query() -> None:
    bm25_index, dense_index, provider = build_test_indexes()

    results = retrieve_hybrid(
        query="   ",
        bm25_index=bm25_index,
        dense_index=dense_index,
        embedding_provider=provider,
        top_k=5,
    )

    assert results == []


def test_retrieve_hybrid_rejects_invalid_top_k() -> None:
    bm25_index, dense_index, provider = build_test_indexes()

    try:
        retrieve_hybrid(
            query="Tibet cultural tour",
            bm25_index=bm25_index,
            dense_index=dense_index,
            embedding_provider=provider,
            top_k=0,
        )
    except ValueError as error:
        assert "top_k must be greater than 0" in str(error)
    else:
        raise AssertionError("Expected ValueError for invalid top_k.")


def test_retrieve_hybrid_rejects_candidate_top_k_smaller_than_top_k() -> None:
    bm25_index, dense_index, provider = build_test_indexes()

    try:
        retrieve_hybrid(
            query="Tibet cultural tour",
            bm25_index=bm25_index,
            dense_index=dense_index,
            embedding_provider=provider,
            top_k=5,
            candidate_top_k=3,
        )
    except ValueError as error:
        assert "candidate_top_k must be greater than or equal to top_k" in str(error)
    else:
        raise AssertionError("Expected ValueError for invalid candidate_top_k.")



