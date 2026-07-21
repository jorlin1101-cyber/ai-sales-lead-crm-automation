from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.rag.source_mapper import sanitize_retrieved_sources


def make_chunk(chunk_id: str, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_type="notion_page",
        notion_page_id=f"private-page-{rank}",
        source_title=f"Source {rank}",
        source_path=f"Private/Path/{rank}",
        doc_type="pricing",
        region="general",
        product_name=None,
        section=f"Section {rank}",
        text=f"Private text {rank}",
        score=1 / rank,
        rank=rank,
        retrieval_source="fusion",
    )


def test_source_mapper_deduplicates_limits_and_reassigns_public_rank() -> None:
    chunks = [
        make_chunk("chunk-1", 5),
        make_chunk("chunk-1", 6),
        make_chunk("chunk-2", 8),
        make_chunk("chunk-3", 9),
        make_chunk("chunk-4", 10),
    ]

    sources = sanitize_retrieved_sources(chunks)

    assert [source.chunk_id for source in sources] == ["chunk-1", "chunk-2", "chunk-3"]
    assert [source.rank for source in sources] == [1, 2, 3]
    assert set(sources[0].model_dump()) == {
        "chunk_id",
        "source_title",
        "section",
        "rank",
    }


def test_source_mapper_does_not_expose_private_chunk_fields() -> None:
    source_json = sanitize_retrieved_sources([make_chunk("chunk-1", 1)])[0].model_dump_json()

    assert "notion_page_id" not in source_json
    assert "source_path" not in source_json
    assert "Private text" not in source_json
