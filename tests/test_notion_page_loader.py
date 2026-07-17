import json
from pathlib import Path
from pydantic import ValidationError

import pytest

from lead_cleaner.rag.notion_page_loader import (
    load_page_id_map,
    _extract_plain_text,
    _block_to_text,
    _blocks_to_text,
    build_raw_notion_page,
    fetch_notion_blocks_recursive,
    fetch_notion_page_last_edited_time,
)
from lead_cleaner.rag.schemas import RawNotionPage


def test_load_page_id_map_reads_valid_mapping(tmp_path: Path):
    page_id_map_path = tmp_path / "notion_page_tree_ids.json"
    source_path = "AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour"
    page_id_map = {
        source_path: "page_western_sichuan_private_tour",
    }
    page_id_map_path.write_text(
        json.dumps(page_id_map),
        encoding="utf-8",
    )

    result = load_page_id_map(page_id_map_path)

    assert result == page_id_map
    assert result[source_path] == "page_western_sichuan_private_tour"


def test_load_page_id_map_raises_when_file_missing(tmp_path: Path):
    missing_path = tmp_path / "missing_notion_page_tree_ids.json"

    with pytest.raises(FileNotFoundError):
        load_page_id_map(missing_path)


def test_load_page_id_map_raises_when_top_level_is_not_dict(tmp_path: Path):
    page_id_map_path = tmp_path / "notion_page_tree_ids.json"
    page_id_map_path.write_text(
        json.dumps(["page_1", "page_2"]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_page_id_map(page_id_map_path)


def test_load_page_id_map_raises_when_source_path_key_is_not_str(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    page_id_map_path = tmp_path / "notion_page_tree_ids.json"
    page_id_map_path.write_text("{}", encoding="utf-8")

    def fake_json_load(file):
        return {123: "page_id_123"}

    monkeypatch.setattr(
        "lead_cleaner.rag.notion_page_loader.json.load",
        fake_json_load,
    )

    with pytest.raises(ValueError):
        load_page_id_map(page_id_map_path)


def test_load_page_id_map_raises_when_page_id_value_is_not_str(tmp_path: Path):
    page_id_map_path = tmp_path / "notion_page_tree_ids.json"
    source_path = "AI Sales Knowledge Base/Products/Tibet/Tibet Cultural Tour"
    page_id_map_path.write_text(
        json.dumps({source_path: 12345}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_page_id_map(page_id_map_path)


def test_extract_plain_text_joins_rich_text_items():
    rich_text_items = [
        {"plain_text": "Western Sichuan "},
        {"plain_text": "Private Tour"},
    ]

    result = _extract_plain_text(rich_text_items)

    assert result == "Western Sichuan Private Tour"


def test_block_to_text_converts_paragraph_block():
    block = {
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {"plain_text": "Western Sichuan Private Tour"},
            ]
        },
    }

    result = _block_to_text(block)

    assert result == "Western Sichuan Private Tour"


def test_block_to_text_converts_heading_blocks():
    heading_1 = {
        "type": "heading_1",
        "heading_1": {
            "rich_text": [
                {"plain_text": "Western Sichuan"},
            ]
        },
    }
    heading_2 = {
        "type": "heading_2",
        "heading_2": {
            "rich_text": [
                {"plain_text": "Suitable For"},
            ]
        },
    }
    heading_3 = {
        "type": "heading_3",
        "heading_3": {
            "rich_text": [
                {"plain_text": "Sales Notes"},
            ]
        },
    }

    assert _block_to_text(heading_1) == "# Western Sichuan"
    assert _block_to_text(heading_2) == "## Suitable For"
    assert _block_to_text(heading_3) == "### Sales Notes"


def test_block_to_text_converts_list_blocks():
    bulleted_block = {
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"plain_text": "Private custom tour"},
            ]
        },
    }
    numbered_block = {
        "type": "numbered_list_item",
        "numbered_list_item": {
            "rich_text": [
                {"plain_text": "Confirm group size"},
            ]
        },
    }

    assert _block_to_text(bulleted_block) == "- Private custom tour"
    assert _block_to_text(numbered_block) == "1. Confirm group size"


def test_block_to_text_returns_empty_string_for_unsupported_block_type():
    block = {
        "type": "divider",
        "divider": {},
    }

    result = _block_to_text(block)

    assert result == ""


def test_blocks_to_text_joins_supported_blocks_with_newlines():
    blocks = [
        {
            "type": "heading_1",
            "heading_1": {
                "rich_text": [
                    {"plain_text": "Western Sichuan Private Tour"},
                ]
            },
        },
        {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"plain_text": "Suitable for travel agencies."},
                ]
            },
        },
        {
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    {"plain_text": "Private custom groups"},
                ]
            },
        },
    ]

    result = _blocks_to_text(blocks)

    assert result == (
        "# Western Sichuan Private Tour\nSuitable for travel agencies.\n- Private custom groups"
    )


def test_blocks_to_text_skips_empty_block_outputs():
    blocks = [
        {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"plain_text": "Valid paragraph."},
                ]
            },
        },
        {
            "type": "divider",
            "divider": {},
        },
        {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [],
            },
        },
    ]

    result = _blocks_to_text(blocks)

    assert result == "Valid paragraph."


def test_build_raw_notion_page_builds_page_from_blocks():
    source_path = "AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour"
    blocks = [
        {
            "type": "heading_1",
            "heading_1": {
                "rich_text": [
                    {"plain_text": "Western Sichuan Private Tour"},
                ]
            },
        },
        {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"plain_text": "Suitable for travel agencies."},
                ]
            },
        },
        {
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    {"plain_text": "Private custom groups"},
                ]
            },
        },
    ]

    raw_page = build_raw_notion_page(
        notion_page_id="page_western_sichuan_private_tour",
        source_path=source_path,
        blocks=blocks,
        last_edited_time="2026-06-16T10:00:00Z",
    )

    assert isinstance(raw_page, RawNotionPage)
    assert raw_page.notion_page_id == "page_western_sichuan_private_tour"
    assert raw_page.source_title == "Western Sichuan Private Tour"
    assert raw_page.source_path == source_path
    assert raw_page.raw_blocks == blocks
    assert raw_page.last_edited_time == "2026-06-16T10:00:00Z"
    assert raw_page.raw_text == (
        "# Western Sichuan Private Tour\nSuitable for travel agencies.\n- Private custom groups"
    )


def test_build_raw_notion_page_raises_when_source_path_is_empty():
    with pytest.raises(ValueError):
        build_raw_notion_page(
            notion_page_id="page_empty",
            source_path="",
            blocks=[
                {
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {"plain_text": "Valid text."},
                        ]
                    },
                }
            ],
            last_edited_time="2026-06-16T10:00:00Z",
        )


def test_build_raw_notion_page_raises_when_blocks_produce_empty_text():
    source_path = "AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour"

    with pytest.raises(ValidationError):
        build_raw_notion_page(
            notion_page_id="page_western_sichuan_private_tour",
            source_path=source_path,
            blocks=[
                {
                    "type": "divider",
                    "divider": {},
                }
            ],
            last_edited_time="2026-06-16T10:00:00Z",
        )


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        (
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"plain_text": "Hello world"}],
                },
            },
            "Hello world",
        ),
        (
            {
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"plain_text": "Suitable For"}],
                },
            },
            "## Suitable For",
        ),
        (
            {
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"plain_text": "Private custom groups"}],
                },
            },
            "- Private custom groups",
        ),
        (
            {
                "type": "toggle",
                "toggle": {
                    "rich_text": [{"plain_text": "Pricing Notes"}],
                },
            },
            "### Pricing Notes",
        ),
    ],
)
def test_block_to_text_handles_supported_blocks(block, expected) -> None:
    assert _block_to_text(block) == expected


def test_fetch_notion_blocks_recursive_fetches_nested_children(monkeypatch) -> None:
    fake_responses = {
        "page_1": [
            {"id": "heading_1", "type": "heading_2", "has_children": False},
            {"id": "toggle_1", "type": "toggle", "has_children": True},
            {"id": "paragraph_1", "type": "paragraph", "has_children": False},
        ],
        "toggle_1": [
            {"id": "bullet_1", "type": "bulleted_list_item", "has_children": False},
        ],
    }

    calls = []

    def fake_fetch_notion_blocks(block_id: str, notion_api_key: str):
        calls.append(block_id)
        return fake_responses[block_id]

    monkeypatch.setattr(
        "lead_cleaner.rag.notion_page_loader.fetch_notion_blocks",
        fake_fetch_notion_blocks,
    )

    result = fetch_notion_blocks_recursive("page_1", "fake_key")

    assert [block["id"] for block in result] == [
        "heading_1",
        "toggle_1",
        "bullet_1",
        "paragraph_1",
    ]
    assert calls == ["page_1", "toggle_1"]


def test_fetch_notion_blocks_recursive_skips_child_page(monkeypatch) -> None:
    fake_responses = {
        "page_1": [
            {"id": "child_page_1", "type": "child_page", "has_children": True},
            {"id": "paragraph_1", "type": "paragraph", "has_children": False},
        ],
    }

    calls = []

    def fake_fetch_notion_blocks(block_id: str, notion_api_key: str):
        calls.append(block_id)
        return fake_responses[block_id]

    monkeypatch.setattr(
        "lead_cleaner.rag.notion_page_loader.fetch_notion_blocks",
        fake_fetch_notion_blocks,
    )

    result = fetch_notion_blocks_recursive("page_1", "fake_key")

    assert [block["id"] for block in result] == [
        "child_page_1",
        "paragraph_1",
    ]
    assert calls == ["page_1"]


def test_fetch_notion_blocks_recursive_requires_id_for_nested_block(monkeypatch) -> None:
    fake_responses = {
        "page_1": [
            {"type": "toggle", "has_children": True},
        ],
    }

    def fake_fetch_notion_blocks(block_id: str, notion_api_key: str):
        return fake_responses[block_id]

    monkeypatch.setattr(
        "lead_cleaner.rag.notion_page_loader.fetch_notion_blocks",
        fake_fetch_notion_blocks,
    )

    with pytest.raises(RuntimeError, match="missing a valid id"):
        fetch_notion_blocks_recursive("page_1", "fake_key")


def test_fetch_notion_blocks_recursive_raises_when_max_depth_exceeded() -> None:
    with pytest.raises(
        RuntimeError,
        match="Maximum Notion block recursion depth exceeded: 5",
    ):
        fetch_notion_blocks_recursive(
            block_id="page_1",
            notion_api_key="fake_key",
            max_depth=5,
            current_depth=6,
        )


def test_fetch_notion_page_last_edited_time(monkeypatch) -> None:
    def fake_request_notion_json(url: str, notion_api_key: str):
        return {
            "object": "page",
            "id": "page_1",
            "last_edited_time": "2026-06-16T10:00:00Z",
        }

    monkeypatch.setattr(
        "lead_cleaner.rag.notion_page_loader._request_notion_json",
        fake_request_notion_json,
    )

    result = fetch_notion_page_last_edited_time("page_1", "fake_key")

    assert result == "2026-06-16T10:00:00Z"


def test_fetch_notion_page_last_edited_time_raises_when_missing(monkeypatch) -> None:
    def fake_request_notion_json(url: str, notion_api_key: str):
        return {
            "object": "page",
            "id": "page_1",
        }

    monkeypatch.setattr(
        "lead_cleaner.rag.notion_page_loader._request_notion_json",
        fake_request_notion_json,
    )

    with pytest.raises(RuntimeError, match="missing a valid last_edited_time"):
        fetch_notion_page_last_edited_time("page_1", "fake_key")
