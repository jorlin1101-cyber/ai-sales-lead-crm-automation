from lead_cleaner.rag.chunker import (
    chunk_document_by_heading_sections,
    chunk_documents_by_heading_sections,
    split_text_by_heading_sections,
)
from lead_cleaner.rag.schemas import KnowledgeDocument


def make_document(
    source_path: str = "AI Sales Knowledge Base/Pricing/Private Tour Pricing Rules",
    text: str | None = None,
) -> KnowledgeDocument:
    return KnowledgeDocument(
        source_type="notion_page",
        notion_page_id="page_1",
        source_title="Private Tour Pricing Rules",
        source_path=source_path,
        doc_type="pricing",
        region="general",
        product_name=None,
        status="Active",
        priority="P0",
        tags=["pricing", "quotation"],
        last_edited_time="2026-06-16T10:00:00Z",
        text=text
        or (
            "# Private Tour Pricing Rules\n"
            "\n"
            "## Pricing Variables\n"
            "- Group size affects quotation.\n"
            "- Hotel level affects cost.\n"
            "\n"
            "## Group Size\n"
            "- 2–5 travelers can usually use a smaller vehicle.\n"
            "- 15–25 travelers may require a coach.\n"
        ),
    )


def test_split_text_by_heading_sections_returns_sections() -> None:
    document = make_document()

    result = split_text_by_heading_sections(document.text)

    assert result == [
        (
            "Pricing Variables",
            "## Pricing Variables\n"
            "- Group size affects quotation.\n"
            "- Hotel level affects cost.",
        ),
        (
            "Group Size",
            "## Group Size\n"
            "- 2–5 travelers can usually use a smaller vehicle.\n"
            "- 15–25 travelers may require a coach.",
        ),
    ]


def test_chunk_document_by_heading_sections_creates_chunks_with_metadata() -> None:
    document = make_document()

    chunks = chunk_document_by_heading_sections(document)

    assert len(chunks) == 2

    first_chunk = chunks[0]
    assert first_chunk.source_type == "notion_page"
    assert first_chunk.notion_page_id == "page_1"
    assert first_chunk.source_title == "Private Tour Pricing Rules"
    assert first_chunk.source_path == document.source_path
    assert first_chunk.doc_type == "pricing"
    assert first_chunk.region == "general"
    assert first_chunk.product_name is None
    assert first_chunk.section == "Pricing Variables"
    assert first_chunk.chunk_index == 0
    assert first_chunk.chunk_strategy == "heading_section"
    assert first_chunk.last_edited_time == "2026-06-16T10:00:00Z"
    assert first_chunk.text.startswith(
        "# Private Tour Pricing Rules\n## Pricing Variables"
    )
    assert "Group size affects quotation." in first_chunk.text


def test_chunk_document_by_heading_sections_creates_stable_chunk_ids() -> None:
    document = make_document()

    first_run = chunk_document_by_heading_sections(document)
    second_run = chunk_document_by_heading_sections(document)

    assert [chunk.chunk_id for chunk in first_run] == [
        chunk.chunk_id for chunk in second_run
    ]


def test_chunk_document_by_heading_sections_falls_back_to_single_chunk() -> None:
    document = make_document(
        text="Plain text without markdown headings.",
    )

    chunks = chunk_document_by_heading_sections(document)

    assert len(chunks) == 1
    assert chunks[0].section == "Private Tour Pricing Rules"
    assert chunks[0].text == (
        "# Private Tour Pricing Rules\n"
        "Plain text without markdown headings."
    )

def test_chunk_documents_by_heading_sections_preserves_document_order() -> None:
    first_document = make_document(source_path="path_1")
    second_document = make_document(source_path="path_2")

    chunks = chunk_documents_by_heading_sections(
        documents=[first_document, second_document],
    )

    assert [chunk.source_path for chunk in chunks] == [
        "path_1",
        "path_1",
        "path_2",
        "path_2",
    ]
