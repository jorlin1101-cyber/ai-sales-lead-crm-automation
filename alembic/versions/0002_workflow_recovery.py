"""Add recovery leases and auditable workflow events, without altering existing records."""

from alembic import op
from lead_cleaner.services.conversation_store import conversation_leases, workflow_events

revision = "0002_workflow_recovery"
down_revision = "0001_postgresql_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in (conversation_leases, workflow_events):
        table.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in (workflow_events, conversation_leases):
        table.drop(op.get_bind(), checkfirst=True)
