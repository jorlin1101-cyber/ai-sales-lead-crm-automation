import json

import pytest

import scripts.build_knowledge_chunks as build_chunks
from lead_cleaner.rag.schemas import KnowledgeChunk, KnowledgeDocument


def make_document() -> KnowledgeDocument:
    return KnowledgeDocument(
        source_type="notion_page",
        notion_page_id="page_1",
        source_title="Private Tour Pricing Rules",
        source_path="AI Sales Knowledge Base/Pricing/Private Tour Pricing Rules",
        doc_type="pricing",
        region="general",
        product_name=None,
        status="Active",
        priority="P0",
        tags=["pricing", "quotation"],
        last_edited_time="2026-06-16T10:00:00Z",
        text=(
            "# Private Tour Pricing Rules\n\n## Group Size\n- 15–25 travelers may require a coach."
        ),
    )


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
        text=(
            "# Private Tour Pricing Rules\n## Group Size\n- 15–25 travelers may require a coach."
        ),
        last_edited_time="2026-06-16T10:00:00Z",
    )


def model_to_dict(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")

    return model.dict()


def test_load_knowledge_documents_loads_json_list(tmp_path) -> None:
    input_path = tmp_path / "notion_pages.json"
    input_path.write_text(
        json.dumps([model_to_dict(make_document())], ensure_ascii=False),
        encoding="utf-8",
    )

    documents = build_chunks.load_knowledge_documents(input_path)

    assert len(documents) == 1
    assert documents[0].source_title == "Private Tour Pricing Rules"
    assert documents[0].doc_type == "pricing"
    assert documents[0].region == "general"


def test_load_knowledge_documents_raises_when_file_missing(tmp_path) -> None:
    input_path = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError, match="Knowledge documents file not found"):
        build_chunks.load_knowledge_documents(input_path)


def test_load_knowledge_documents_raises_when_json_is_not_list(tmp_path) -> None:
    input_path = tmp_path / "notion_pages.json"
    input_path.write_text(
        json.dumps({"source_title": "Wrong Shape"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must contain a JSON list"):
        build_chunks.load_knowledge_documents(input_path)


def test_save_knowledge_chunks_writes_json_file(tmp_path) -> None:
    output_path = tmp_path / "knowledge_snapshot" / "knowledge_chunks.json"

    build_chunks.save_knowledge_chunks(
        chunks=[make_chunk()],
        output_path=output_path,
    )

    saved_data = json.loads(output_path.read_text(encoding="utf-8"))

    assert output_path.exists()
    assert len(saved_data) == 1
    assert saved_data[0]["chunk_id"] == "chunk_1"
    assert saved_data[0]["source_title"] == "Private Tour Pricing Rules"
    assert saved_data[0]["section"] == "Group Size"
    assert saved_data[0]["chunk_strategy"] == "heading_section"


def test_main_builds_and_saves_chunks(tmp_path, monkeypatch, capsys) -> None:
    input_path = tmp_path / "notion_pages.json"
    output_path = tmp_path / "knowledge_chunks.json"

    input_path.write_text(
        json.dumps([model_to_dict(make_document())], ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(build_chunks, "DEFAULT_INPUT_PATH", input_path)
    monkeypatch.setattr(build_chunks, "DEFAULT_OUTPUT_PATH", output_path)

    build_chunks.main()

    saved_data = json.loads(output_path.read_text(encoding="utf-8"))
    captured = capsys.readouterr()

    assert len(saved_data) == 1
    assert saved_data[0]["section"] == "Group Size"
    assert "Built knowledge chunks." in captured.out
    assert "Documents: 1" in captured.out
    assert "Chunks: 1" in captured.out
