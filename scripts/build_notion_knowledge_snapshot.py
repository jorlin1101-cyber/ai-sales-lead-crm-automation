import json
import os
from pathlib import Path
from typing import Any

from lead_cleaner.rag.metadata_resolver import load_manifest, resolve_metadata
from lead_cleaner.rag.notion_page_loader import (
    build_raw_notion_page,
    fetch_notion_blocks_recursive,
    fetch_notion_page_last_edited_time,
    load_page_id_map,
)
from lead_cleaner.rag.schemas import KnowledgeDocument


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "config" / "knowledge_manifest.yml"
DEFAULT_PAGE_ID_MAP_PATH = (
    PROJECT_ROOT / "data" / "knowledge_snapshot" / "notion_page_tree_ids.json"
)
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "knowledge_snapshot" / "notion_pages.json"


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")

    return value


def get_manifest_source_paths(manifest: dict[str, Any]) -> list[str]:
    pages = manifest.get("pages")

    if not isinstance(pages, dict):
        raise ValueError("Manifest 'pages' must be a dictionary.")

    return list(pages.keys())


def build_knowledge_document_for_source_path(
    source_path: str,
    page_id: str,
    manifest: dict[str, Any],
    notion_api_key: str,
) -> KnowledgeDocument:
    blocks = fetch_notion_blocks_recursive(
        block_id=page_id,
        notion_api_key=notion_api_key,
    )

    last_edited_time = fetch_notion_page_last_edited_time(
        page_id=page_id,
        notion_api_key=notion_api_key,
    )

    raw_page = build_raw_notion_page(
        notion_page_id=page_id,
        source_path=source_path,
        blocks=blocks,
        last_edited_time=last_edited_time,
    )

    return resolve_metadata(raw_page, manifest)


def build_knowledge_snapshot(
    manifest: dict[str, Any],
    page_id_map: dict[str, str],
    notion_api_key: str,
) -> list[KnowledgeDocument]:
    documents: list[KnowledgeDocument] = []

    for source_path in get_manifest_source_paths(manifest):
        page_id = page_id_map.get(source_path)

        if not page_id:
            raise ValueError(f"Missing Notion page id for manifest source_path: {source_path}")

        document = build_knowledge_document_for_source_path(
            source_path=source_path,
            page_id=page_id,
            manifest=manifest,
            notion_api_key=notion_api_key,
        )
        documents.append(document)

    return documents


def knowledge_document_to_dict(document: KnowledgeDocument) -> dict[str, Any]:
    if hasattr(document, "model_dump"):
        return document.model_dump(mode="json")

    return document.dict()


def save_knowledge_documents(
    documents: list[KnowledgeDocument],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    serialized_documents = [knowledge_document_to_dict(document) for document in documents]

    output_path.write_text(
        json.dumps(
            serialized_documents,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    notion_api_key = get_required_env("NOTION_API_KEY")

    manifest = load_manifest(DEFAULT_MANIFEST_PATH)
    page_id_map = load_page_id_map(DEFAULT_PAGE_ID_MAP_PATH)

    documents = build_knowledge_snapshot(
        manifest=manifest,
        page_id_map=page_id_map,
        notion_api_key=notion_api_key,
    )

    save_knowledge_documents(
        documents=documents,
        output_path=DEFAULT_OUTPUT_PATH,
    )

    print("Built Notion knowledge snapshot.")
    print(f"Documents: {len(documents)}")
    print(f"Output: {DEFAULT_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
