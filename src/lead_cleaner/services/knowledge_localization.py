"""Translations are valid only for the exact source revision they were reviewed against."""

import json
import re
from pathlib import Path

from lead_cleaner.rag.schemas import RetrievedChunk

TRANSLATIONS_PATH = Path("data/knowledge_snapshot/translations.zh.json")


def source_bullets(chunk: RetrievedChunk, language: str) -> list[str]:
    if language == "zh" and TRANSLATIONS_PATH.is_file():
        entries = json.loads(TRANSLATIONS_PATH.read_text(encoding="utf-8"))
        for entry in entries:
            if entry["chunk_id"] == chunk.chunk_id and entry["source_text"] == chunk.text:
                return list(entry["bullets"])
    # Never silently substitute a translation of a different version.
    lines = [
        line.strip().removeprefix("- ").removeprefix("• ")
        for line in chunk.text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if language == "zh" and not re.search(r"[\u4e00-\u9fff]", chunk.text):
        lines = [f"原文（译文待复核）：{line}" for line in lines]
    return lines[:3]
