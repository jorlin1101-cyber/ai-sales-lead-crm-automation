"""Local operator workspace with Qwen enabled and CRM delivery disabled."""

import os
import re
from pathlib import Path

from lead_cleaner.api.main import create_app
from lead_cleaner.config import Settings


def _read_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    key_file = os.environ.get("DASHSCOPE_API_KEY_FILE", "").strip()
    if not key and key_file:
        content = Path(key_file).read_text(encoding="utf-8")
        match = re.search(r"sk-[A-Za-z0-9._-]{20,}", content)
        key = match.group(0) if match else ""
    if not key:
        raise RuntimeError("Set DASHSCOPE_API_KEY or DASHSCOPE_API_KEY_FILE.")
    return key


def create_live_preview():
    database = os.environ.get("REVIEW_DATABASE_PATH", "data/runtime/conversations-v2.sqlite3")
    return create_app(
        settings=Settings(
            _env_file=None,
            app_mode="rule_only",
            allow_network=True,
            conversation_llm_enabled=True,
            dashscope_api_key=_read_key(),
            dashscope_model=os.environ.get("DASHSCOPE_MODEL", "qwen3.7-plus"),
            rag_backend="keyword_rrf",
            rag_required=True,
            notion_crm_enabled=False,
            conversation_database_url=None,
            conversation_auto_create_schema=True,
            conversation_db_path=Path(database),
            service_access_mode="local",
        )
    )
