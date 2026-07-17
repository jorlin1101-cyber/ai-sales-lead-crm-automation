#!/usr/bin/env python3
"""
Notion Knowledge Base Page Tree Discoverer (RAG v1).

Reads an existing Notion page tree recursively, builds a source_path → page_id
mapping, and saves it to data/knowledge_snapshot/notion_page_tree_ids.json.

This script only reads — it never creates or modifies any Notion page.

Usage:
    python scripts/discover_notion_knowledge_tree.py

Environment Variables:
    NOTION_API_KEY                   (required) Notion integration token
    NOTION_KNOWLEDGE_ROOT_PAGE_ID    (required) root page of the knowledge base

The root page title is validated against EXPECTED_ROOT_TITLE so that the
generated source_path first segment always matches config/knowledge_manifest.yml.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
OUTPUT_PATH = Path("data/knowledge_snapshot/notion_page_tree_ids.json")
EXPECTED_ROOT_TITLE = "AI Sales Knowledge Base"

# Retry / back-off limits
_MAX_RETRY_429 = 3
_MAX_RETRY_5XX = 3
_BACKOFF_BASE = 1.0  # seconds


# ---------------------------------------------------------------------------
# Resilient HTTP request helper
# ---------------------------------------------------------------------------

def _request(
    client: httpx.Client,
    headers: dict[str, str],
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """Issue an HTTP GET and retry on transient Notion API errors.

    - 429 (rate limit): reads Retry-After header and waits, up to
      ``_MAX_RETRY_429`` attempts.
    - 500 / 502 / 503 / 504 (server errors): exponential backoff
      (``_BACKOFF_BASE * 2 ** n``), up to ``_MAX_RETRY_5XX`` attempts.

    The two retry budgets are tracked independently — exhausting one does
    not consume the other.

    Any other status code is returned as-is so the caller can decide how to
    handle it (typically checking for 200 and raising on anything else).
    """
    retries_429 = 0
    retries_5xx = 0

    while True:
        response = client.get(url, headers=headers, **kwargs)

        if response.status_code == 429:
            retries_429 += 1
            if retries_429 > _MAX_RETRY_429:
                raise RuntimeError(
                    f"Notion API rate limited after {_MAX_RETRY_429} retries: "
                    f"{response.status_code} {response.text}"
                )
            retry_after = _parse_retry_after(response)
            print(f"  [retry] 429 — waiting {retry_after}s (retry {retries_429})")
            time.sleep(retry_after)
            continue

        if response.status_code in (500, 502, 503, 504):
            retries_5xx += 1
            if retries_5xx > _MAX_RETRY_5XX:
                raise RuntimeError(
                    f"Notion API {response.status_code} after "
                    f"{_MAX_RETRY_5XX} retries: {response.text}"
                )
            wait = _BACKOFF_BASE * (2 ** (retries_5xx - 1))
            print(
                f"  [retry] {response.status_code} — "
                f"waiting {wait:.1f}s (retry {retries_5xx})"
            )
            time.sleep(wait)
            continue

        return response


def _parse_retry_after(response: httpx.Response) -> float:
    """Read Retry-After header; fall back to 5 seconds if absent or unparsable."""
    raw = response.headers.get("Retry-After")
    if raw is not None:
        try:
            return float(raw)
        except ValueError:
            pass
    return 5.0


# ---------------------------------------------------------------------------
# Notion API helpers
# ---------------------------------------------------------------------------

def _notion_headers(api_key: str) -> dict[str, str]:
    """Standard Notion API headers."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _list_child_blocks(
    client: httpx.Client,
    headers: dict[str, str],
    block_id: str,
) -> list[dict[str, Any]]:
    """Return all child blocks of *block_id*. Handles pagination."""
    results: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        response = _request(
            client,
            headers,
            f"{NOTION_API_BASE}/blocks/{block_id}/children",
            params=params,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to list children of {block_id}: "
                f"{response.status_code} {response.text}"
            )
        data = response.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return results


def _get_page_title(
    client: httpx.Client,
    headers: dict[str, str],
    page_id: str,
) -> str:
    """Retrieve the title of a Notion page.

    Raises RuntimeError if the page cannot be read or no title is found.
    """
    response = _request(
        client,
        headers,
        f"{NOTION_API_BASE}/pages/{page_id}",
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to retrieve page {page_id}: "
            f"{response.status_code} {response.text}"
        )

    data = response.json()
    properties = data.get("properties", {})

    for prop_name, prop_value in properties.items():
        if prop_value.get("type") == "title":
            title_parts = prop_value.get("title", [])
            if title_parts:
                return "".join(
                    part.get("plain_text", "") for part in title_parts
                )

    raise RuntimeError(f"Could not find title property on page {page_id}")


# ---------------------------------------------------------------------------
# Recursive discovery
# ---------------------------------------------------------------------------

def _discover_recursive(
    client: httpx.Client,
    headers: dict[str, str],
    page_id: str,
    current_path: str,
    id_map: dict[str, str],
) -> None:
    """Recursively discover child_page blocks beneath *page_id*.

    For each child_page found, records its source_path → page_id in *id_map*
    and recurses into it.

    Raises RuntimeError if two child pages under the same parent share a title
    (which would cause a source_path collision in id_map).
    """
    blocks = _list_child_blocks(client, headers, page_id)

    # Track titles seen among child_page blocks under this parent
    seen_titles: set[str] = set()

    for block in blocks:
        if block.get("type") != "child_page":
            continue

        child_info = block.get("child_page", {})
        title = child_info.get("title", "")
        if not title:
            continue

        if title in seen_titles:
            raise RuntimeError(
                f"Duplicate child_page title '{title}' found under "
                f"'{current_path}'. Notion allows multiple pages with the "
                f"same name — rename one of them to keep source_path unique."
            )
        seen_titles.add(title)

        child_id = block["id"]
        child_path = f"{current_path}/{title}"

        id_map[child_path] = child_id
        print(f"  {child_path}")

        # Recurse into this child page
        _discover_recursive(client, headers, child_id, child_path, id_map)


# ---------------------------------------------------------------------------
# Dry-run simulation helpers
# ---------------------------------------------------------------------------

# Known tree shape (same structure as create script) — used only in dry-run /
# CI mode so the script produces a plausible output without calling the API.
_KNOWN_TREE: dict[str, Any] = {
    "Products": {
        "Western Sichuan": {"Western Sichuan Private Tour": None},
        "Tibet": {"Tibet Cultural Tour": None},
        "Yunnan": {"Yunnan Family Tour": None},
    },
    "Destinations": {
        "Western Sichuan Destination Overview": None,
        "Tibet Destination Overview": None,
        "Yunnan Destination Overview": None,
    },
    "Pricing": {
        "Private Tour Pricing Rules": None,
    },
    "FAQ": {
        "Travel Permit and Payment FAQ": None,
    },
}


def _to_fake_id(path: str) -> str:
    """Convert a source_path to a stable fake page ID for dry-run mode.

    Example:
        "AI Sales Knowledge Base/Products/Western Sichuan"
        → "dry-run-ai-sales-knowledge-base-products-western-sichuan"
    """
    slug = path.lower().replace("/", "-").replace(" ", "-")
    return f"dry-run-{slug}"


def _discover_dry_run(root_name: str, root_id: str) -> dict[str, str]:
    """Simulate discovery using the known tree shape (no API calls)."""
    id_map: dict[str, str] = {root_name: root_id}
    print(f"  {root_name}  (dry-run)")

    def _walk(subtree: dict[str, Any], prefix: str) -> None:
        for node_name, node_value in subtree.items():
            path = f"{prefix}/{node_name}"
            print(f"  {path}  (dry-run)")
            id_map[path] = _to_fake_id(path)
            if isinstance(node_value, dict):
                _walk(node_value, path)

    print()
    _walk(_KNOWN_TREE, root_name)
    return id_map


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def _validate_env() -> tuple[str, str]:
    """Read and validate environment variables. Returns (api_key, root_id)."""
    api_key = os.getenv("NOTION_API_KEY")
    if not api_key:
        print("ERROR: Missing NOTION_API_KEY environment variable.", file=sys.stderr)
        sys.exit(1)

    root_id = os.getenv("NOTION_KNOWLEDGE_ROOT_PAGE_ID")
    if not root_id:
        print(
            "ERROR: Missing NOTION_KNOWLEDGE_ROOT_PAGE_ID environment variable. "
            "This script requires a root page ID to discover from.",
            file=sys.stderr,
        )
        sys.exit(1)

    return api_key, root_id


def _is_dry_run(api_key: str) -> bool:
    """Determine whether the script should run in dry-run / CI mode."""
    return api_key.startswith("test_") or os.getenv("CI", "").lower() in ("1", "true")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Recursively discover the Notion knowledge base page tree."""
    api_key, root_id = _validate_env()
    dry_run = _is_dry_run(api_key)

    if dry_run:
        print("Dry-run mode: no API calls will be made.")
        print()
        print("Discovered pages:")
        id_map = _discover_dry_run(root_name=EXPECTED_ROOT_TITLE, root_id=root_id)
    else:
        print(f"Discovering page tree from root: {root_id}")
        print()

        with httpx.Client(timeout=30.0) as client:
            headers = _notion_headers(api_key)

            # Retrieve root page title from Notion
            try:
                root_title = _get_page_title(client, headers, root_id)
            except RuntimeError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                sys.exit(1)

            # Validate root title matches expected value
            if root_title != EXPECTED_ROOT_TITLE:
                print(
                    f"ERROR: Root page title mismatch.\n"
                    f"  Expected: {EXPECTED_ROOT_TITLE}\n"
                    f"  Got:      {root_title}\n\n"
                    f"Either rename the Notion root page to "
                    f"'{EXPECTED_ROOT_TITLE}', or update "
                    f"EXPECTED_ROOT_TITLE and config/knowledge_manifest.yml "
                    f"to match the actual title.",
                    file=sys.stderr,
                )
                sys.exit(1)

            id_map: dict[str, str] = {root_title: root_id}
            print(f"  Root: {root_title}")

            # Recursively discover children
            try:
                _discover_recursive(client, headers, root_id, root_title, id_map)
            except RuntimeError as exc:
                print(f"ERROR: Tree discovery failed — {exc}", file=sys.stderr)
                sys.exit(1)

    # --- Summary ---
    print()
    print(f"Discovered pages: {len(id_map)} total")
    for path, pid in id_map.items():
        print(f"  - {path}: {pid}")

    # Save to output file
    output_path = OUTPUT_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(id_map, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nSaved page ID mapping to: {output_path}")


if __name__ == "__main__":
    main()
