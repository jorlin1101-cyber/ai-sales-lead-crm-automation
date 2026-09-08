"""Isolated offline UI review; never uses local .env secrets or live CRM."""

from pathlib import Path
from tempfile import mkdtemp
import os

from lead_cleaner.api.main import create_app
from lead_cleaner.config import Settings


def create_preview():
    return create_app(
        settings=Settings(
            _env_file=None,
            app_mode="rule_only",
            allow_network=False,
            notion_crm_enabled=False,
            conversation_database_url=None,
            conversation_auto_create_schema=True,
            conversation_db_path=(
                Path(os.environ["REVIEW_DATABASE_PATH"])
                if os.environ.get("REVIEW_DATABASE_PATH")
                else Path(mkdtemp(prefix="leadflow-review-")) / "review.sqlite3"
            ),
            service_access_mode="local",
        )
    )
