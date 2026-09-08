from __future__ import annotations

import hashlib
from contextlib import contextmanager, nullcontext
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    insert,
    select,
    update,
    delete,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from lead_cleaner.schemas.conversation import (
    ConversationChannel,
    ConversationFact,
    ConversationMessageRequest,
    ConversationRetrievalTrace,
    ConversationState,
    ConversationSummary,
    ConversationTimelineItem,
    ConversationTurnResult,
    ReplyDraft,
    DraftReviewRequest,
)


class ConversationIdempotencyConflictError(RuntimeError):
    """The same external message id was reused with a different payload."""


class ConversationMessageProcessingError(RuntimeError):
    """A duplicate message exists but its first processing attempt has not completed."""


metadata = MetaData()
json_type = JSON().with_variant(JSONB(), "postgresql")

conversations = Table(
    "conversations",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("external_conversation_id", String(200), nullable=False),
    Column("channel", String(32), nullable=False),
    Column("source", String(100), nullable=False),
    Column("sender_name", String(200)),
    Column("sender_email", String(320)),
    Column("company_name", String(300)),
    Column("state", String(32), nullable=False),
    Column("context_summary", Text, nullable=False, default=""),
    Column("turn_number", Integer, nullable=False, default=0),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "channel", "source", "external_conversation_id", name="uq_conversation_external"
    ),
)

conversation_messages = Table(
    "conversation_messages",
    metadata,
    Column("id", String(100), primary_key=True),
    Column(
        "conversation_id",
        String(100),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("external_message_id", String(300), nullable=False),
    Column("direction", String(16), nullable=False),
    Column("channel", String(32), nullable=False),
    Column("source", String(100), nullable=False),
    Column("subject", String(500)),
    Column("raw_text", Text, nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("processing_status", String(32), nullable=False),
    Column("turn_number", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("channel", "source", "external_message_id", name="uq_message_external"),
    UniqueConstraint("conversation_id", "turn_number", name="uq_conversation_turn"),
)

conversation_facts = Table(
    "conversation_facts",
    metadata,
    Column(
        "conversation_id",
        String(100),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("fact_key", String(100), primary_key=True),
    Column("fact_value", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("source_message_id", String(100), nullable=False),
    Column("version", Integer, nullable=False, default=1),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

conversation_fact_history = Table(
    "conversation_fact_history",
    metadata,
    Column("id", String(100), primary_key=True),
    Column(
        "conversation_id",
        String(100),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("fact_key", String(100), nullable=False),
    Column("fact_value", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("source_message_id", String(100), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

analysis_runs = Table(
    "analysis_runs",
    metadata,
    Column("id", String(100), primary_key=True),
    Column(
        "conversation_id",
        String(100),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "message_id",
        String(100),
        ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("result_json", json_type, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

reply_drafts = Table(
    "reply_drafts",
    metadata,
    Column("id", String(100), primary_key=True),
    Column(
        "conversation_id",
        String(100),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "message_id",
        String(100),
        ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("channel", String(32), nullable=False),
    Column("draft_json", json_type, nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

rag_retrieval_runs = Table(
    "rag_retrieval_runs",
    metadata,
    Column("id", String(100), primary_key=True),
    Column(
        "conversation_id",
        String(100),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "message_id",
        String(100),
        ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("decision", String(32), nullable=False),
    Column("reason", String(100), nullable=False),
    Column("queries", json_type, nullable=False),
    Column("retrieval_method", String(50), nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

rag_retrieval_hits = Table(
    "rag_retrieval_hits",
    metadata,
    Column("id", String(100), primary_key=True),
    Column(
        "retrieval_run_id",
        String(100),
        ForeignKey("rag_retrieval_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("chunk_id", String(200), nullable=False),
    Column("source_title", String(500), nullable=False),
    Column("section", String(500), nullable=False),
    Column("rank", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("retrieval_run_id", "chunk_id", name="uq_retrieval_hit_chunk"),
)

reply_draft_sources = Table(
    "reply_draft_sources",
    metadata,
    Column(
        "draft_id",
        String(100),
        ForeignKey("reply_drafts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "retrieval_hit_id",
        String(100),
        ForeignKey("rag_retrieval_hits.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("citation_order", Integer, nullable=False),
)

# Additive migration: old conversations, messages and fact history are preserved.
conversation_leases = Table(
    "conversation_leases",
    metadata,
    Column("conversation_id", String(100), primary_key=True),
    Column("token", String(100), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

workflow_events = Table(
    "workflow_events",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("conversation_id", String(100), nullable=False, index=True),
    Column("kind", String(50), nullable=False),
    Column("payload", json_type, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | str) -> str:
    return value.isoformat(timespec="seconds") if isinstance(value, datetime) else value


def _payload_hash(subject: str | None, text: str) -> str:
    return hashlib.sha256(f"{subject or ''}\0{text}".encode()).hexdigest()


def _database_url(value: str | Path) -> tuple[str, dict[str, Any]]:
    raw = str(value)
    if raw == ":memory:":
        return "sqlite+pysqlite:///:memory:", {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }
    if "://" not in raw:
        path = Path(raw)
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+pysqlite:///{path.resolve().as_posix()}", {
            "connect_args": {"check_same_thread": False}
        }
    return raw, {}


class ConversationStore:
    """Transactional conversation repository; PostgreSQL is the production backend."""

    def __init__(
        self, database_url: str | Path = ":memory:", *, create_schema: bool = True
    ) -> None:
        resolved_url, options = _database_url(database_url)
        self.engine: Engine = create_engine(
            resolved_url,
            pool_pre_ping=True,
            future=True,
            **options,
        )
        if create_schema:
            metadata.create_all(self.engine)

    @property
    def dialect_name(self) -> str:
        return self.engine.dialect.name

    def close(self) -> None:
        self.engine.dispose()

    @contextmanager
    def processing_lease(self, conversation_id: str) -> Iterator[str]:
        """Short DB transactions only; token fences workers that outlive their lease."""
        token = uuid4().hex
        now = _now()
        with self.engine.begin() as connection:
            claimed = connection.execute(
                update(conversation_leases)
                .where(
                    (conversation_leases.c.conversation_id == conversation_id)
                    & (conversation_leases.c.expires_at < now)
                )
                .values(token=token, expires_at=now + timedelta(minutes=5))
            ).rowcount
        if not claimed:
            try:
                with self.engine.begin() as connection:
                    connection.execute(
                        insert(conversation_leases).values(
                            conversation_id=conversation_id,
                            token=token,
                            expires_at=now + timedelta(minutes=5),
                        )
                    )
            except IntegrityError as error:
                raise ConversationMessageProcessingError(
                    "Conversation is processing another request; retry the same message ID."
                ) from error
        try:
            yield token
        finally:
            with self.engine.begin() as connection:
                connection.execute(
                    delete(conversation_leases).where(
                        (conversation_leases.c.conversation_id == conversation_id)
                        & (conversation_leases.c.token == token)
                    )
                )

    def assert_lease(self, connection: Connection, conversation_id: str, token: str) -> None:
        row = connection.execute(
            select(conversation_leases.c.token)
            .where(
                (conversation_leases.c.conversation_id == conversation_id)
                & (conversation_leases.c.token == token)
                & (conversation_leases.c.expires_at > _now())
            )
            .with_for_update()
        ).first()
        if row is None:
            raise ConversationMessageProcessingError(
                "Processing lease expired; retry this message."
            )

    def mark_failed(self, message_id: str, conversation_id: str, token: str) -> None:
        with self.engine.begin() as connection:
            self.assert_lease(connection, conversation_id, token)
            connection.execute(
                update(conversation_messages)
                .where(
                    (conversation_messages.c.id == message_id)
                    & (conversation_messages.c.processing_status == "processing")
                )
                .values(processing_status="failed")
            )

    def get_or_create_conversation(
        self,
        request: ConversationMessageRequest,
    ) -> ConversationSummary:
        lookup = (
            (conversations.c.channel == request.channel)
            & (conversations.c.source == request.source)
            & (conversations.c.external_conversation_id == request.external_conversation_id)
        )
        with self.engine.connect() as connection:
            row = connection.execute(select(conversations).where(lookup)).mappings().first()
        if row is None:
            now = _now()
            conversation_id = f"conv_{uuid4().hex}"
            try:
                with self.engine.begin() as connection:
                    connection.execute(
                        insert(conversations).values(
                            id=conversation_id,
                            external_conversation_id=request.external_conversation_id,
                            channel=request.channel,
                            source=request.source,
                            sender_name=request.sender_name,
                            sender_email=request.sender_email,
                            company_name=request.company_name,
                            state="new",
                            context_summary="",
                            turn_number=0,
                            created_at=now,
                            updated_at=now,
                        )
                    )
            except IntegrityError:
                pass
            with self.engine.connect() as connection:
                row = connection.execute(select(conversations).where(lookup)).mappings().one()
        return self._summary(row)

    def find_message_result(
        self,
        *,
        channel: ConversationChannel,
        source: str,
        external_message_id: str,
        subject: str | None,
        text: str,
        request: ConversationMessageRequest | None = None,
    ) -> ConversationTurnResult | None:
        statement = (
            select(
                conversation_messages.c.payload_hash,
                conversation_messages.c.processing_status,
                conversation_messages.c.conversation_id,
                analysis_runs.c.result_json,
            )
            .select_from(
                conversation_messages.outerjoin(
                    analysis_runs,
                    analysis_runs.c.message_id == conversation_messages.c.id,
                )
            )
            .where(
                (conversation_messages.c.channel == channel)
                & (conversation_messages.c.source == source)
                & (conversation_messages.c.external_message_id == external_message_id)
            )
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            return None
        if row["payload_hash"] != _payload_hash(subject, text):
            raise ConversationIdempotencyConflictError(
                "external_message_id was already used with different content"
            )
        if request is not None:
            with self.engine.connect() as connection:
                owner = (
                    connection.execute(
                        select(conversations).where(conversations.c.id == row["conversation_id"])
                    )
                    .mappings()
                    .one()
                )
            if (
                owner["external_conversation_id"] != request.external_conversation_id
                or owner["sender_email"] != request.sender_email
                or owner["sender_name"] != request.sender_name
                or owner["company_name"] != request.company_name
            ):
                raise ConversationIdempotencyConflictError(
                    "Message ID belongs to a different conversation or sender."
                )
        if row["result_json"] is None:
            return None  # The processing lease arbitrates active/retry/crash recovery.
        result = ConversationTurnResult.model_validate(row["result_json"])
        return result.model_copy(update={"idempotency_status": "duplicate"})

    def append_message(
        self,
        *,
        conversation_id: str,
        external_message_id: str,
        channel: ConversationChannel,
        source: str,
        subject: str | None,
        text: str,
        recover: bool = False,
    ) -> tuple[str, int]:
        message_id = f"msg_{uuid4().hex}"
        now = _now()
        if recover:
            with self.engine.begin() as connection:
                pending = (
                    connection.execute(
                        select(conversation_messages)
                        .where(
                            (conversation_messages.c.conversation_id == conversation_id)
                            & (conversation_messages.c.processing_status != "processed")
                        )
                        .order_by(conversation_messages.c.turn_number)
                    )
                    .mappings()
                    .first()
                )
                if pending:
                    if pending["external_message_id"] != external_message_id or pending[
                        "payload_hash"
                    ] != _payload_hash(subject, text):
                        raise ConversationMessageProcessingError(
                            "Retry the previous failed message before starting another turn."
                        )
                    connection.execute(
                        update(conversation_messages)
                        .where(conversation_messages.c.id == pending["id"])
                        .values(processing_status="processing")
                    )
                    return pending["id"], pending["turn_number"]
        try:
            with self.engine.begin() as connection:
                row = (
                    connection.execute(
                        select(conversations.c.turn_number)
                        .where(conversations.c.id == conversation_id)
                        .with_for_update()
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise ValueError("Conversation does not exist")
                turn_number = int(row["turn_number"]) + 1
                connection.execute(
                    insert(conversation_messages).values(
                        id=message_id,
                        conversation_id=conversation_id,
                        external_message_id=external_message_id,
                        direction="inbound",
                        channel=channel,
                        source=source,
                        subject=subject,
                        raw_text=text,
                        payload_hash=_payload_hash(subject, text),
                        processing_status="processing",
                        turn_number=turn_number,
                        created_at=now,
                    )
                )
                connection.execute(
                    update(conversations)
                    .where(conversations.c.id == conversation_id)
                    .values(turn_number=turn_number, updated_at=now)
                )
        except IntegrityError as error:
            raise ConversationMessageProcessingError(
                "message or turn already exists; retry with the same idempotency key"
            ) from error
        return message_id, turn_number

    def get_facts(self, conversation_id: str) -> list[ConversationFact]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(conversation_facts)
                .where(conversation_facts.c.conversation_id == conversation_id)
                .order_by(conversation_facts.c.fact_key)
            ).mappings()
            return [
                ConversationFact(
                    key=row["fact_key"],
                    value=row["fact_value"],
                    status=row["status"],
                    confidence=row["confidence"],
                    source_message_id=row["source_message_id"],
                )
                for row in rows
            ]

    def upsert_fact(
        self,
        conversation_id: str,
        fact: ConversationFact,
        *,
        replace: bool = False,
        connection: Connection | None = None,
    ) -> ConversationFact:
        now = _now()
        with (
            nullcontext(connection) if connection is not None else self.engine.begin()
        ) as connection:
            current = (
                connection.execute(
                    select(conversation_facts)
                    .where(
                        (conversation_facts.c.conversation_id == conversation_id)
                        & (conversation_facts.c.fact_key == fact.key)
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            value = fact.value
            status = fact.status
            confidence = fact.confidence
            version = 1
            if current is not None:
                version = int(current["version"]) + 1
                current_value = str(current["fact_value"])
                if current_value != fact.value:
                    equivalent_range = fact.key == "travel_date" and (
                        current_value in fact.value or fact.value in current_value
                    )
                    if not equivalent_range and not replace and fact.status != "human_confirmed":
                        value = f"{current_value} / {fact.value}"
                        status = "conflicted"
                        confidence = min(float(current["confidence"]), fact.confidence)
                connection.execute(
                    update(conversation_facts)
                    .where(
                        (conversation_facts.c.conversation_id == conversation_id)
                        & (conversation_facts.c.fact_key == fact.key)
                    )
                    .values(
                        fact_value=value,
                        status=status,
                        confidence=confidence,
                        source_message_id=fact.source_message_id,
                        version=version,
                        updated_at=now,
                    )
                )
            else:
                connection.execute(
                    insert(conversation_facts).values(
                        conversation_id=conversation_id,
                        fact_key=fact.key,
                        fact_value=value,
                        status=status,
                        confidence=confidence,
                        source_message_id=fact.source_message_id,
                        version=version,
                        updated_at=now,
                    )
                )
            connection.execute(
                insert(conversation_fact_history).values(
                    id=f"fact_history_{uuid4().hex}",
                    conversation_id=conversation_id,
                    fact_key=fact.key,
                    fact_value=value,
                    status=status,
                    confidence=confidence,
                    source_message_id=fact.source_message_id,
                    version=version,
                    created_at=now,
                )
            )
        return ConversationFact(
            key=fact.key,
            value=value,
            status=status,
            confidence=confidence,
            source_message_id=fact.source_message_id,
        )

    def get_recent_messages(self, conversation_id: str, *, limit: int = 6) -> list[str]:
        statement = (
            select(conversation_messages.c.raw_text)
            .where(conversation_messages.c.conversation_id == conversation_id)
            .order_by(conversation_messages.c.turn_number.desc())
            .limit(limit)
        )
        with self.engine.connect() as connection:
            values = list(connection.execute(statement).scalars())
        history = list(reversed(values))
        with self.engine.connect() as connection:
            sent = connection.execute(
                select(workflow_events.c.payload)
                .where(
                    (workflow_events.c.conversation_id == conversation_id)
                    & (workflow_events.c.kind == "draft_review")
                )
                .order_by(workflow_events.c.created_at.desc())
                .limit(20)
            ).scalars()
            replies = [
                f"Sales reply (sent): {event['draft']['body_text']}"
                for event in sent
                if event["action"] == "record_sent"
            ][:3]
        return history[-3:] + list(reversed(replies))

    def latest_result(self, conversation_id: str) -> ConversationTurnResult | None:
        with self.engine.connect() as connection:
            payload = connection.execute(
                select(analysis_runs.c.result_json)
                .where(analysis_runs.c.conversation_id == conversation_id)
                .order_by(analysis_runs.c.created_at.desc())
                .limit(1)
            ).scalar()
        if not payload:
            return None
        result = ConversationTurnResult.model_validate(payload)
        with self.engine.connect() as connection:
            draft = connection.execute(
                select(reply_drafts.c.draft_json).where(
                    reply_drafts.c.id == result.reply_draft.draft_id
                )
            ).scalar()
        return (
            result.model_copy(update={"reply_draft": ReplyDraft.model_validate(draft)})
            if draft
            else result
        )

    def put_event(
        self,
        kind: str,
        owner: str,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
        connection: Connection | None = None,
    ) -> str:
        event_id = event_id or f"event_{uuid4().hex}"
        with (
            nullcontext(connection) if connection is not None else self.engine.begin()
        ) as connection:
            connection.execute(
                insert(workflow_events).values(
                    id=event_id,
                    conversation_id=owner,
                    kind=kind,
                    payload=payload,
                    created_at=_now(),
                )
            )
        return event_id

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(workflow_events).where(workflow_events.c.id == event_id))
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def update_event(self, event_id: str, payload: dict[str, Any]) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(workflow_events)
                .where(workflow_events.c.id == event_id)
                .values(payload=payload)
            )

    def bind_owner(self, conversation_id: str, owner: str) -> None:
        try:
            self.put_event(
                "owner", conversation_id, {"owner": owner}, event_id=f"owner_{conversation_id}"
            )
        except IntegrityError:
            event = self.get_event(f"owner_{conversation_id}")
            if not event or event["payload"]["owner"] != owner:
                raise ConversationIdempotencyConflictError("Conversation ownership mismatch.")

    def list_conversations(self, owner: str, *, limit: int = 50) -> list[dict[str, Any]]:
        latest_subject = (
            select(conversation_messages.c.subject)
            .where(conversation_messages.c.conversation_id == conversations.c.id)
            .order_by(conversation_messages.c.turn_number.desc())
            .limit(1)
            .correlate(conversations)
            .scalar_subquery()
        )
        statement = select(conversations, latest_subject.label("subject")).order_by(
            conversations.c.updated_at.desc()
        )
        if owner != "operator":
            statement = statement.join(
                workflow_events, workflow_events.c.conversation_id == conversations.c.id
            ).where(
                (workflow_events.c.kind == "owner")
                & (workflow_events.c.payload["owner"].as_string() == owner)
            )
        statement = statement.limit(limit)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        result = []
        for row in rows:
            if owner != "operator":
                event = self.get_event(f"owner_{row['id']}")
                if not event or event["payload"]["owner"] != owner:
                    continue
            result.append(
                {
                    **self._summary(row).model_dump(),
                    "external_conversation_id": row["external_conversation_id"],
                    "sender_name": row["sender_name"],
                    "sender_email": row["sender_email"],
                    "subject": row["subject"],
                }
            )
            if len(result) >= limit:
                break
        return result

    def review_draft(
        self, conversation_id: str, draft_id: str, request: DraftReviewRequest, operator: str
    ) -> ReplyDraft:
        with self.processing_lease(conversation_id) as token, self.engine.begin() as connection:
            self.assert_lease(connection, conversation_id, token)
            row = (
                connection.execute(
                    select(reply_drafts)
                    .where(
                        (reply_drafts.c.id == draft_id)
                        & (reply_drafts.c.conversation_id == conversation_id)
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ValueError("Draft not found")
            draft = ReplyDraft.model_validate(row["draft_json"])
            if draft.draft_version != request.expected_version:
                raise ConversationIdempotencyConflictError(
                    "Draft changed; reload before reviewing."
                )
            if draft.status in {"suppressed", "sent"}:
                raise ConversationIdempotencyConflictError(
                    "Suppressed or sent drafts cannot be changed."
                )
            current_turn = connection.execute(
                select(conversations.c.turn_number).where(conversations.c.id == conversation_id)
            ).scalar_one()
            if draft.turn_number != current_turn:
                raise ConversationIdempotencyConflictError(
                    "A newer customer message requires a new review."
                )
            if request.action == "record_sent":
                if draft.status != "approved" or not request.external_receipt or request.body_text:
                    raise ValueError(
                        "Record sending only for an unchanged approved draft with a receipt."
                    )
                status = "sent"
            else:
                status = {"save": "ready_for_review", "approve": "approved", "reject": "rejected"}[
                    request.action
                ]
            body = request.body_text if request.body_text is not None else draft.body_text
            draft = ReplyDraft.model_validate(
                {
                    **draft.model_dump(),
                    "draft_version": draft.draft_version + 1,
                    "status": status,
                    "body_text": body,
                    "display_text": body,
                }
            )
            connection.execute(
                update(reply_drafts)
                .where(reply_drafts.c.id == draft_id)
                .values(status=draft.status, draft_json=draft.model_dump(mode="json"))
            )
            self.put_event(
                "draft_review",
                conversation_id,
                {
                    "operator": operator,
                    "action": request.action,
                    "receipt": request.external_receipt,
                    "draft": draft.model_dump(mode="json"),
                },
                connection=connection,
            )
            return draft

    def save_turn(
        self,
        *,
        conversation_id: str,
        message_id: str,
        result: object,
        draft: object,
        retrieval: ConversationRetrievalTrace,
        state: ConversationState,
        context_summary: str,
        facts: list[ConversationFact] | None = None,
        lease_token: str | None = None,
    ) -> None:
        now = _now()
        result_payload: Any = (
            result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        )
        draft_payload: dict[str, Any] = (
            draft.model_dump(mode="json")
            if hasattr(draft, "model_dump")
            else cast(dict[str, Any], draft)
        )
        retrieval_run_id = f"retrieval_{uuid4().hex}"
        with self.engine.begin() as connection:
            if lease_token is not None:
                self.assert_lease(connection, conversation_id, lease_token)
            for fact in facts or []:
                self.upsert_fact(conversation_id, fact, replace=True, connection=connection)
            connection.execute(
                insert(analysis_runs).values(
                    id=f"analysis_{uuid4().hex}",
                    conversation_id=conversation_id,
                    message_id=message_id,
                    result_json=result_payload,
                    created_at=now,
                )
            )
            connection.execute(
                insert(reply_drafts).values(
                    id=draft_payload["draft_id"],
                    conversation_id=conversation_id,
                    message_id=message_id,
                    channel=draft_payload["channel"],
                    draft_json=draft_payload,
                    status=draft_payload["status"],
                    created_at=now,
                )
            )
            connection.execute(
                insert(rag_retrieval_runs).values(
                    id=retrieval_run_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    decision=retrieval.decision,
                    reason=retrieval.reason,
                    queries=retrieval.queries,
                    retrieval_method=retrieval.retrieval_method,
                    status="completed",
                    created_at=now,
                )
            )
            cited_source_ids = set(draft_payload.get("source_ids", []))
            for source in retrieval.sources:
                hit_id = f"hit_{uuid4().hex}"
                connection.execute(
                    insert(rag_retrieval_hits).values(
                        id=hit_id,
                        retrieval_run_id=retrieval_run_id,
                        chunk_id=source.chunk_id,
                        source_title=source.source_title,
                        section=source.section,
                        rank=source.rank,
                        created_at=now,
                    )
                )
                if source.chunk_id in cited_source_ids:
                    connection.execute(
                        insert(reply_draft_sources).values(
                            draft_id=draft_payload["draft_id"],
                            retrieval_hit_id=hit_id,
                            citation_order=source.rank,
                        )
                    )
            connection.execute(
                update(conversation_messages)
                .where(conversation_messages.c.id == message_id)
                .values(processing_status="processed")
            )
            connection.execute(
                update(conversations)
                .where(conversations.c.id == conversation_id)
                .values(state=state, context_summary=context_summary, updated_at=now)
            )

    def get_summary(self, conversation_id: str) -> ConversationSummary | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(conversations).where(conversations.c.id == conversation_id)
                )
                .mappings()
                .first()
            )
        return self._summary(row) if row is not None else None

    def timeline(self, conversation_id: str) -> list[ConversationTimelineItem]:
        statement = (
            select(conversation_messages, reply_drafts.c.draft_json)
            .select_from(
                conversation_messages.outerjoin(
                    reply_drafts,
                    reply_drafts.c.message_id == conversation_messages.c.id,
                )
            )
            .where(conversation_messages.c.conversation_id == conversation_id)
            .order_by(conversation_messages.c.turn_number)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        items: list[ConversationTimelineItem] = []
        for row in rows:
            draft_payload = row["draft_json"]
            items.append(
                ConversationTimelineItem(
                    message_id=row["id"],
                    direction=row["direction"],
                    channel=row["channel"],
                    turn_number=row["turn_number"],
                    subject=row["subject"],
                    text_preview=row["raw_text"][:240],
                    created_at=_iso(row["created_at"]),
                    draft_status=draft_payload["status"] if draft_payload else None,
                    reply_text_preview=(
                        draft_payload["body_text"][:240] if draft_payload else None
                    ),
                    source_count=len(draft_payload.get("source_ids", [])) if draft_payload else 0,
                    text=row["raw_text"],
                    reply_text=draft_payload["body_text"] if draft_payload else None,
                    processing_status=row["processing_status"],
                )
            )
        return items

    @staticmethod
    def _summary(row: RowMapping) -> ConversationSummary:
        return ConversationSummary(
            conversation_id=row["id"],
            channel=row["channel"],
            source=row["source"],
            state=row["state"],
            turn_number=row["turn_number"],
            context_summary=row["context_summary"],
            updated_at=_iso(row["updated_at"]),
        )
