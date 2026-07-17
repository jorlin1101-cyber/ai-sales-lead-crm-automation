import pytest
from pydantic import ValidationError

from lead_cleaner.rag.schemas import KnowledgeChunk


def make_chunk() -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id="chunk_1",
        source_type="notion_page",
        notion_page_id="page_1",
        source_title="Private Tour Pricing Rules",
        source_path="AI Sales Knowledge Base/Pricing/Private Tour Pricing Rules",
        doc_type="pricing",
        region="general",
        product_name=None,
        section="Group Size",
        chunk_index=0,
        chunk_strategy="heading_section",
        text="# Private Tour Pricing Rules\n## Group Size\n- 15–25 travelers may require a coach.",
        last_edited_time="2026-06-16T10:00:00Z",
    )


def test_knowledge_chunk_accepts_valid_data() -> None:
    chunk = make_chunk()

    assert chunk.chunk_id == "chunk_1"
    assert chunk.source_type == "notion_page"
    assert chunk.doc_type == "pricing"
    assert chunk.region == "general"
    assert chunk.section == "Group Size"
    assert chunk.chunk_strategy == "heading_section"


def test_knowledge_chunk_rejects_empty_text() -> None:
    data = make_chunk().model_dump()
    data["text"] = ""

    with pytest.raises(ValidationError):
        KnowledgeChunk(**data)


def test_knowledge_chunk_rejects_negative_chunk_index() -> None:
    data = make_chunk().model_dump()
    data["chunk_index"] = -1

    with pytest.raises(ValidationError):
        KnowledgeChunk(**data)


def test_knowledge_chunk_rejects_invalid_doc_type() -> None:
    data = make_chunk().model_dump()
    data["doc_type"] = "company"

    with pytest.raises(ValidationError):
        KnowledgeChunk(**data)
