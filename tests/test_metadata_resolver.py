from pathlib import Path
from pydantic import ValidationError

import pytest

from lead_cleaner.rag.metadata_resolver import get_manifest_entry, load_manifest, resolve_metadata
from lead_cleaner.rag.schemas import RawNotionPage, KnowledgeDocument

def test_load_manifest_valid_data(tmp_path: Path):
    manifest_path = tmp_path / "knowledge_manifest.yml"
    manifest_path.write_text(
        """
    pages:
        "AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour":
            doc_type: product
            region: western_sichuan
            product_name: Western Sichuan Private Tour
            priority: P0
            status: Active
            tags:
            - western_sichuan
            - private_tour
    """,
        encoding="utf-8",
    )

    manifest = load_manifest(manifest_path)

    assert "pages" in manifest
    assert isinstance(manifest["pages"], dict)
    assert(
         "AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour"
        in manifest["pages"]
    )


def test_load_manifest_raises_when_file_missing(tmp_path: Path):
    missing_path = tmp_path / "missing_manifest.yml"

    with pytest.raises(FileNotFoundError):
        load_manifest(missing_path)


def test_load_manifest_when_top_level_is_not_dict(tmp_path: Path):
    manifest_path = tmp_path / "knowledge_manifest.yml"
    manifest_path.write_text(
    """
- product
- destination
- pricing
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_manifest(manifest_path)


def test_load_manifest_raises_when_pages_key_missing(tmp_path: Path):
    manifest_path = tmp_path / "knowledge_manifest.yml"
    manifest_path.write_text(
    """
documents:
  "AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour":
    doc_type: product
    region: western_sichuan
""",
    encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_manifest(manifest_path)


def test_load_manifest_raises_when_pages_is_not_dict(tmp_path: Path):
    manifest_path = tmp_path / "knowledge_manifest.yml"
    manifest_path.write_text(
        """
pages:
  - Western Sichuan Private Tour
  - Tibet Cultural Tour
""",
    encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_manifest(manifest_path)


def test_get_manifest_entry_returns_entry_when_source_path_exists():
    source_path = "AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour"
    manifest = {
        "pages": {
            source_path: {
                "doc_type": "product",
                "region": "western_sichuan",
                "product_name": "Western Sichuan Private Tour",
                "priority": "P0",
                "status": "Active",
                "tags": ["western_sichuan", "private_tour"],
            }
        }
    }

    entry = get_manifest_entry(source_path, manifest)

    assert entry["doc_type"] == "product"
    assert entry["region"] == "western_sichuan"
    assert entry["tags"] == ["western_sichuan", "private_tour"]


def test_get_manifest_entry_raises_when_source_path_missing():
    existing_source_path = "AI Sales Knowledge Base/Products/Tibet/Tibet Cultural Tour"
    missing_source_path = "AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour"
    manifest = {
        "pages": {
            existing_source_path: {
                "doc_type": "product",
                "region": "tibet",
                "product_name": "Tibet Cultural Tour",
                "priority": "P0",
                "status": "Active",
                "tags": ["tibet", "cultural_tour"],
            }
        }
    }
    with pytest.raises(ValueError) as exc_info:
        get_manifest_entry(missing_source_path, manifest)

    assert missing_source_path in str(exc_info.value)


def test_resolve_metadata_converts_raw_page_to_knowledge_document():
    source_path = "AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour"
    raw_page = RawNotionPage(
        notion_page_id="page_western_sichuan_private_tour",
        source_title="Western Sichuan Private Tour",
        source_path=source_path,
        raw_text="Western Sichuan Private Tour is suitable for travel agencies, private custom groups, and travelers looking for Tibetan culture, plateau landscapes, and flexible routing.",
        raw_blocks=[
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "plain_text": "Western Sichuan Private Tour is suitable for travel agencies and private custom groups."
                        }
                    ]
                },
            }
        ],
        last_edited_time="2026-06-16T10:00:00Z",
    )

    manifest = {
        "pages": {
            source_path: {
                "doc_type": "product",
                "region": "western_sichuan",
                "product_name": "Western Sichuan Private Tour",
                "priority": "P0",
                "status": "Active",
                "tags": ["western_sichuan", "private_tour"],
            }
        }
    }

    document = resolve_metadata(raw_page, manifest)

    assert document.source_type == "notion_page"
    assert document.notion_page_id == raw_page.notion_page_id
    assert document.source_path == raw_page.source_path
    assert document.text == raw_page.raw_text
    assert document.doc_type == "product"
    assert document.region == "western_sichuan"
    assert document.product_name == "Western Sichuan Private Tour"
    assert document.status == "Active"
    assert document.tags == ["western_sichuan", "private_tour"]
    assert isinstance(document, KnowledgeDocument)


def test_resolve_metadata_raises_when_doc_type_is_invalid():
    source_path = "AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour"
    raw_page = RawNotionPage(
        notion_page_id="page_western_sichuan_private_tour",
        source_title="Western Sichuan Private Tour",
        source_path=source_path,
        raw_text="Western Sichuan Private Tour is suitable for travel agencies, private custom groups, and travelers looking for Tibetan culture, plateau landscapes, and flexible routing.",
        raw_blocks=[
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "plain_text": "Western Sichuan Private Tour is suitable for travel agencies and private custom groups."
                        }
                    ]
                },
            }
        ],
        last_edited_time="2026-06-16T10:00:00Z",
    )

    manifest = {
        "pages": {
            source_path: {
                "doc_type": "wrong_type",
                "region": "western_sichuan",
                "product_name": "Western Sichuan Private Tour",
                "priority": "P0",
                "status": "Active",
                "tags": ["western_sichuan", "private_tour"],
            }
        }
    }
    with pytest.raises(ValidationError):
        resolve_metadata(raw_page, manifest)

