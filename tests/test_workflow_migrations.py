from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from lead_cleaner.schemas.conversation import ConversationMessageRequest
from lead_cleaner.services.conversation_store import ConversationStore, metadata
from tests.test_conversations import message_payload


def test_additive_recovery_migration_preserves_existing_conversation(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "old.sqlite").as_posix()
    engine = create_engine(url)
    # Simulate the pre-recovery schema, retaining real older records.
    tables = [
        table
        for table in metadata.sorted_tables
        if table.name not in {"conversation_leases", "workflow_events"}
    ]
    metadata.create_all(engine, tables=tables)
    store = ConversationStore(url, create_schema=False)
    summary = store.get_or_create_conversation(
        ConversationMessageRequest(**message_payload("old", "8个人"))
    )
    store.close()
    engine.dispose()
    monkeypatch.setenv("CONVERSATION_DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.stamp(cfg, "0001_postgresql_conversations")
    command.upgrade(cfg, "head")
    store = ConversationStore(url, create_schema=False)
    try:
        assert store.get_summary(summary.conversation_id) == summary
        assert {"conversation_leases", "workflow_events"} <= set(
            inspect(store.engine).get_table_names()
        )
        with store.processing_lease(summary.conversation_id):
            pass
    finally:
        store.close()
