"""
Tests for src/lead_cleaner/rag/schemas.py.

Covers:
- RawNotionPage
- KnowledgeDocument
- KnowledgeChunk
- RetrievedChunk
- metadata_resolver
"""

# ─── Tests will be added alongside the schemas in subsequent commits ───


import pytest
from pydantic import ValidationError

from lead_cleaner.rag.schemas import KnowledgeDocument, RawNotionPage


def test_raw_notion_page_can_be_created_with_valid_data():
    page = RawNotionPage(
        notion_page_id="page_123",
        source_title="Western Sichuan Private Tour",
        source_path="AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour",
        raw_text="This is a valid Notion page text.",
        raw_blocks=[{"type": "paragraph"}],
        last_edited_time="2026-06-15T10:00:00Z",
    )

    assert page.notion_page_id == "page_123"
    assert page.raw_text == "This is a valid Notion page text."


def test_raw_notion_page_rejects_empty_raw_text():
    with pytest.raises(ValidationError):
        RawNotionPage(
            notion_page_id="page_123",
            source_title="Western Sichuan Private Tour",
            source_path="AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour",
            raw_text="",
            raw_blocks=[{"type": "paragraph"}],
            last_edited_time="2026-06-15T10:00:00Z",
        )


def test_knowledge_document_can_be_created_with_valid_metadata():
    document = KnowledgeDocument(
        source_type="notion_page",
        notion_page_id="page_123",
        source_title="Western Sichuan Private Tour",
        source_path="AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour",
        doc_type="product",
        region="western_sichuan",
        product_name="Western Sichuan Private Tour",
        status="Active",
        priority="P0",
        tags=["western_sichuan", "private_tour", "agency"],
        last_edited_time="2026-06-15T10:00:00Z",
        text="This is a normalized knowledge document.",
    )

    assert document.doc_type == "product"
    assert document.region == "western_sichuan"
    assert document.status == "Active"


def test_knowledge_document_rejects_invalid_doc_type():
    with pytest.raises(ValidationError):
        KnowledgeDocument(
            source_type="notion_page",
            notion_page_id="page_123",
            source_title="Western Sichuan Private Tour",
            source_path="AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour",
            doc_type="wrong_type",
            region="western_sichuan",
            product_name="Western Sichuan Private Tour",
            status="Active",
            priority="P0",
            tags=["western_sichuan", "private_tour", "agency"],
            last_edited_time="2026-06-15T10:00:00Z",
            text="This is a normalized knowledge document.",
        )
