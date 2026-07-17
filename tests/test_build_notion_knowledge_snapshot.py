import json

import pytest

import scripts.build_notion_knowledge_snapshot as snapshot_builder
from lead_cleaner.rag.schemas import KnowledgeDocument


def make_document(source_path: str = "path_1") -> KnowledgeDocument:
    return KnowledgeDocument(
        source_type="notion_page",
        notion_page_id="page_1",
        source_title="Test Page",
        source_path=source_path,
        doc_type="product",
        region="western_sichuan",
        product_name="Test Product",
        status="Active",
        priority="P0",
        tags=["test"],
        last_edited_time="2026-06-16T10:00:00Z",
        text="Test knowledge content.",
    )


def test_get_required_env_returns_value(monkeypatch) -> None:
    monkeypatch.setenv("NOTION_API_KEY", "fake_key")

    result = snapshot_builder.get_required_env("NOTION_API_KEY")

    assert result == "fake_key"


def test_get_required_env_raises_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("NOTION_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Missing required environment variable"):
        snapshot_builder.get_required_env("NOTION_API_KEY")


def test_get_manifest_source_paths_returns_page_keys() -> None:
    manifest = {
        "pages": {
            "path_1": {"doc_type": "product"},
            "path_2": {"doc_type": "pricing"},
        }
    }

    result = snapshot_builder.get_manifest_source_paths(manifest)

    assert result == ["path_1", "path_2"]


def test_get_manifest_source_paths_raises_when_pages_is_not_dict() -> None:
    manifest = {
        "pages": ["path_1", "path_2"],
    }

    with pytest.raises(ValueError, match="Manifest 'pages' must be a dictionary"):
        snapshot_builder.get_manifest_source_paths(manifest)


def test_build_knowledge_snapshot_builds_documents_from_manifest_paths(
    monkeypatch,
) -> None:
    manifest = {
        "pages": {
            "path_1": {},
            "path_2": {},
        }
    }
    page_id_map = {
        "path_1": "page_1",
        "path_2": "page_2",
    }

    calls = []

    def fake_build_knowledge_document_for_source_path(
        source_path: str,
        page_id: str,
        manifest: dict,
        notion_api_key: str,
    ) -> KnowledgeDocument:
        calls.append(
            {
                "source_path": source_path,
                "page_id": page_id,
                "notion_api_key": notion_api_key,
            }
        )
        return make_document(source_path=source_path)

    monkeypatch.setattr(
        snapshot_builder,
        "build_knowledge_document_for_source_path",
        fake_build_knowledge_document_for_source_path,
    )

    result = snapshot_builder.build_knowledge_snapshot(
        manifest=manifest,
        page_id_map=page_id_map,
        notion_api_key="fake_key",
    )

    assert [document.source_path for document in result] == ["path_1", "path_2"]
    assert calls == [
        {
            "source_path": "path_1",
            "page_id": "page_1",
            "notion_api_key": "fake_key",
        },
        {
            "source_path": "path_2",
            "page_id": "page_2",
            "notion_api_key": "fake_key",
        },
    ]


def test_build_knowledge_snapshot_raises_when_page_id_is_missing() -> None:
    manifest = {
        "pages": {
            "path_1": {},
        }
    }
    page_id_map = {}

    with pytest.raises(ValueError, match="Missing Notion page id"):
        snapshot_builder.build_knowledge_snapshot(
            manifest=manifest,
            page_id_map=page_id_map,
            notion_api_key="fake_key",
        )


def test_save_knowledge_documents_writes_json_file(tmp_path) -> None:
    output_path = tmp_path / "knowledge_snapshot" / "notion_pages.json"
    document = make_document(source_path="path_1")

    snapshot_builder.save_knowledge_documents(
        documents=[document],
        output_path=output_path,
    )

    saved_data = json.loads(output_path.read_text(encoding="utf-8"))

    assert output_path.exists()
    assert saved_data[0]["source_type"] == "notion_page"
    assert saved_data[0]["source_path"] == "path_1"
    assert saved_data[0]["doc_type"] == "product"
    assert saved_data[0]["region"] == "western_sichuan"
    assert saved_data[0]["text"] == "Test knowledge content."
