import json

import pytest

from lead_cleaner.rag.knowledge_loader import load_knowledge_chunks


def make_chunk(chunk_id: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "source_type": "notion_page",
        "notion_page_id": "private-page-id",
        "source_title": "Pricing Rules",
        "source_path": "Knowledge/Pricing Rules",
        "doc_type": "pricing",
        "region": "general",
        "product_name": None,
        "section": "Pricing Variables",
        "chunk_index": 0,
        "chunk_strategy": "heading_section",
        "text": "Pricing depends on group size.",
        "last_edited_time": "2026-07-01T00:00:00Z",
    }


def test_load_knowledge_chunks_validates_json(tmp_path) -> None:
    path = tmp_path / "chunks.json"
    path.write_text(json.dumps([make_chunk("chunk-1")]), encoding="utf-8")

    chunks = load_knowledge_chunks(path)

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "chunk-1"


def test_load_knowledge_chunks_rejects_duplicate_ids(tmp_path) -> None:
    path = tmp_path / "chunks.json"
    path.write_text(
        json.dumps([make_chunk("chunk-1"), make_chunk("chunk-1")]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate chunk_id"):
        load_knowledge_chunks(path)


def test_load_knowledge_chunks_rejects_empty_snapshot(tmp_path) -> None:
    path = tmp_path / "chunks.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot be empty"):
        load_knowledge_chunks(path)
