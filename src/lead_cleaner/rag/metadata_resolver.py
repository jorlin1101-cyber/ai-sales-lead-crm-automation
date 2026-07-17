import yaml

from typing import Any
from pathlib import Path

from lead_cleaner.rag.schemas import RawNotionPage, KnowledgeDocument


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as file:
        manifest = yaml.safe_load(file)

    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a dictionary.")

    if "pages" not in manifest:
        raise ValueError("Manifest must contain a 'pages' key.")

    if not isinstance(manifest["pages"], dict):
        raise ValueError("Manifest 'pages' must be a dictionary.")

    return manifest


def get_manifest_entry(source_path: str, manifest: dict[str, Any]) -> dict[str, Any]:
    pages = manifest["pages"]

    if source_path not in pages:
        raise ValueError(f"Missing manifest entry for source_path: {source_path}")

    return pages[source_path]


def resolve_metadata(raw_page: RawNotionPage, manifest: dict[str, Any]) -> KnowledgeDocument:
    entry = get_manifest_entry(raw_page.source_path, manifest)

    return KnowledgeDocument(
        source_type="notion_page",
        notion_page_id=raw_page.notion_page_id,
        source_title=raw_page.source_title,
        source_path=raw_page.source_path,
        last_edited_time=raw_page.last_edited_time,
        text=raw_page.raw_text,
        doc_type=entry["doc_type"],
        region=entry["region"],
        product_name=entry["product_name"],
        status=entry["status"],
        priority=entry["priority"],
        tags=entry["tags"],
    )
