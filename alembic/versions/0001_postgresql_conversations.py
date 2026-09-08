"""Create PostgreSQL conversation, fact, RAG evidence, and reply tables."""

from collections.abc import Sequence

from alembic import op

from lead_cleaner.services.conversation_store import metadata


revision: str = "0001_postgresql_conversations"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    metadata.drop_all(bind=op.get_bind(), checkfirst=True)
