import json
import httpx

from pathlib import Path
from typing import Any

from lead_cleaner.rag.schemas import RawNotionPage


NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

def load_page_id_map(page_id_map_path: Path) -> dict[str, str]:

    if not page_id_map_path.exists():
        raise FileNotFoundError(f"Page ID map file not found: {page_id_map_path}")

    with page_id_map_path.open("r", encoding="utf-8")as file:
        page_id_map = json.load(file)

    if not isinstance(page_id_map, dict):
        raise ValueError("Page ID map must be a dictionary.")

    for source_path, page_id in page_id_map.items():
        if not isinstance(source_path, str):
            raise ValueError("Page ID map keys must be source_path strings.")

        if not isinstance(page_id, str):
            raise ValueError(
                f"Page ID map value must be a string for source_path: {source_path}"
            )

    return page_id_map

def _extract_plain_text(rich_text_items: list[dict]) -> str:
    texts = []

    for item in rich_text_items:
        text = item.get("plain_text", "")
        texts.append(text)

    return "".join(texts)


def _block_to_text(block: dict[str, Any]) -> str:
    """
    Convert one Notion block into one plain-text line.

    Supported block types:
    - paragraph
    - heading_1
    - heading_2
    - heading_3
    - bulleted_list_item
    - numbered_list_item
    """
    block_type = block.get("type")

    if block_type == "paragraph":
        rich_text_items = block.get("paragraph", {}).get("rich_text", [])
        return _extract_plain_text(rich_text_items)

    if block_type == "heading_1":
        rich_text_items = block.get("heading_1", {}).get("rich_text", [])
        text = _extract_plain_text(rich_text_items)
        return f"# {text}" if text else ""

    if block_type == "heading_2":
        rich_text_items = block.get("heading_2", {}).get("rich_text", [])
        text = _extract_plain_text(rich_text_items)
        return f"## {text}" if text else ""

    if block_type == "heading_3":
        rich_text_items = block.get("heading_3", {}).get("rich_text", [])
        text = _extract_plain_text(rich_text_items)
        return f"### {text}" if text else ""

    if block_type == "bulleted_list_item":
        rich_text_items = block.get("bulleted_list_item", {}).get("rich_text", [])
        text = _extract_plain_text(rich_text_items)
        return f"- {text}" if text else ""

    if block_type == "numbered_list_item":
        rich_text_items = block.get("numbered_list_item", {}).get("rich_text", [])
        text = _extract_plain_text(rich_text_items)
        return f"1. {text}" if text else ""

    if block_type == "toggle":
        rich_text_items = block.get("toggle", {}).get("rich_text", [])
        text = _extract_plain_text(rich_text_items)
        return f"### {text}" if text else ""

    return ""


def _blocks_to_text(blocks: list[dict[str, Any]]) -> str:
    """
    Convert a list of Notion blocks into page-level plain text.

    Empty block outputs are skipped.
    Blocks are joined with newlines to preserve document structure.
    """
    lines = []

    for block in blocks:
        line = _block_to_text(block)

        if line.strip():
            lines.append(line)

    return "\n".join(lines)


def build_raw_notion_page(
    notion_page_id: str,
    source_path: str,
    blocks: list[dict[str, Any]],
    last_edited_time: str,
) -> RawNotionPage:
    """
    Build a RawNotionPage from Notion page blocks.

    This function does not call the Notion API. It only converts already-loaded
    blocks into raw_text and infers source_title from source_path.
    """
    path_parts = [part.strip() for part in source_path.split("/") if part.strip()]

    if not path_parts:
        raise ValueError("source_path must contain at least one path segment.")

    source_title = path_parts[-1]
    raw_text = _blocks_to_text(blocks)

    return RawNotionPage(
        notion_page_id=notion_page_id,
        source_title=source_title,
        source_path=source_path,
        raw_text=raw_text,
        raw_blocks=blocks,
        last_edited_time=last_edited_time,
    )


def _build_notion_headers(notion_api_key: str) -> dict[str, Any]:
    """
    Build HTTP headers required by the Notion API.
    """
    if not notion_api_key:
        raise ValueError("notion_api_key must not be empty.")

    return{
        "Authorization": f"Bearer {notion_api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-type": "application/json",
    }


def _request_notion_json(url: str, notion_api_key: str) -> dict[str, Any]:
    """
    Send a GET request to the Notion API and return the JSON response as a dict.
    """
    headers = _build_notion_headers(notion_api_key)
    try:
        response = httpx.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as error:
        raise RuntimeError(
            f"Notion API request failed with HTTP " f"{error.response.status_code}: {error.response.text}"
        ) from error
    except httpx.RequestError as error:
        raise RuntimeError(f"Notion API request failed: {error}") from error
    except ValueError as error:
        raise RuntimeError("Notion API return invalid JSON") from error

    if not isinstance(data, dict):
        raise RuntimeError("Notion API response must be a dictionary.")

    return data


def fetch_notion_blocks(page_id: str, notion_api_key: str) -> list[dict[str, Any]]:
    if not page_id:
        raise ValueError("page_id must not be empty")

    blocks: list[str[str, Any]] = []
    start_cursor: str | None = None

    while True:
        query_params = {"page_size": "100"}
        if start_cursor:
            query_params["start_cursor"] = start_cursor
        url = httpx.URL(
            f"{NOTION_API_BASE}/blocks/{page_id}/children",
            params=query_params,
        )
        response_data =_request_notion_json(str(url),notion_api_key)

        results = response_data.get("results")
        if not isinstance(results, list):
            raise RuntimeError("Notion API response 'results' must be a list.")

        blocks.extend(results)

        has_more = response_data.get("has_more", False)

        if not has_more:
            break

        next_cursor = response_data.get("next_cursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            raise RuntimeError(
                "Notion API response has_more=True but next_cursor is missing."
            )
        start_cursor = next_cursor

    return blocks


def fetch_notion_blocks_recursive(
    block_id: str,
    notion_api_key: str,
    max_depth: int = 5,
    current_depth: int = 0,
) -> list[dict[str, Any]]:
    """
    Recursively fetch child blocks under a Notion page or block.

    This function fetches first-level children, then recursively fetches
    nested children for blocks such as toggle, list items, columns, and callouts.

    It intentionally does not recurse into child_page blocks, because child pages
    belong to the page tree discovery layer, not the page content loading layer.
    """
    if current_depth > max_depth:
        raise RuntimeError(f"Maximum Notion block recursion depth exceeded: {max_depth}")

    blocks = fetch_notion_blocks(block_id, notion_api_key)
    flattened_blocks: list[dict[str, Any]] = []

    for block in blocks:
        flattened_blocks.append(block)

        block_type = block.get("type")
        has_children = block.get("has_children", False)

        if not has_children:
            continue

        if block_type in {"child_page", "child_database"}:
            continue

        nested_block_id = block.get("id")
        if not isinstance(nested_block_id, str) or not nested_block_id:
            raise RuntimeError("Notion block with children is missing a valid id.")

        nested_blocks = fetch_notion_blocks_recursive(
            block_id=nested_block_id,
            notion_api_key=notion_api_key,
            max_depth=max_depth,
            current_depth=current_depth + 1,
        )

        flattened_blocks.extend(nested_blocks)

    return flattened_blocks


def fetch_notion_page_last_edited_time(
    page_id: str,
    notion_api_key: str,
) -> str:
    """
    Fetch last_edited_time from a Notion page object.
    """
    if not page_id:
        raise ValueError("page_id must not be empty.")

    url = httpx.URL(f"{NOTION_API_BASE}/pages/{page_id}")
    response_data = _request_notion_json(str(url), notion_api_key)

    last_edited_time = response_data.get("last_edited_time")
    if not isinstance(last_edited_time, str) or not last_edited_time:
        raise RuntimeError(
            "Notion page response is missing a valid last_edited_time."
        )

    return last_edited_time


