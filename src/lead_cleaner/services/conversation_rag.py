from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.rag.retriever import RagRetrievalOutcome, RagRetriever
from lead_cleaner.schemas.conversation import ConversationFact


_ACKNOWLEDGEMENT_PATTERN = re.compile(
    r"^\s*(?:(?:好的?|收到|明白了?|知道了?|谢谢(?:你|您)?|感谢|没问题|可以|"
    r"ok(?:ay)?|thanks?)[。！!,.，、\s]*)+$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RetrievalRoute:
    decision: Literal["required", "skipped", "blocked"]
    reason: str


def route_conversation_retrieval(message: str) -> RetrievalRoute:
    if _ACKNOWLEDGEMENT_PATTERN.fullmatch(message):
        return RetrievalRoute(decision="skipped", reason="acknowledgement")
    return RetrievalRoute(decision="required", reason="business_message")


def build_conversation_context_query(
    *,
    current_message: str,
    facts: list[ConversationFact],
    recent_messages: list[str],
) -> str:
    fact_text = " | ".join(
        f"{fact.key}: {fact.value}"
        for fact in facts
        if fact.status not in {"conflicted", "pending"}
    )
    history = " | ".join(message.strip() for message in recent_messages[-3:] if message.strip())
    parts = [f"current message: {current_message.strip()}"]
    if fact_text:
        parts.append(f"confirmed conversation facts: {fact_text}")
    if history:
        parts.append(f"recent conversation: {history}")
    return " | ".join(parts)


@dataclass
class ContextualRagRetriever:
    base: RagRetriever
    context_query: str
    queries: list[str] = field(default_factory=list)
    chunks_by_id: dict[str, RetrievedChunk] = field(default_factory=dict)

    def _remember(self, outcome: RagRetrievalOutcome) -> RagRetrievalOutcome:
        for chunk in outcome.chunks:
            current = self.chunks_by_id.get(chunk.chunk_id)
            if current is None or chunk.score > current.score:
                self.chunks_by_id[chunk.chunk_id] = chunk
        return outcome

    def retrieve(self, query: str) -> RagRetrievalOutcome:
        rewritten_query = f"{self.context_query} | current retrieval intent: {query}"
        self.queries.append(rewritten_query)
        return self._remember(self.base.retrieve(rewritten_query))

    def retrieve_focus(self, query: str) -> RagRetrievalOutcome:
        """Run one auditable business-focused retrieval for the final reply."""

        rewritten_query = f"{self.context_query} | business knowledge focus: {query}"
        self.queries.append(rewritten_query)
        return self._remember(self.base.retrieve(rewritten_query))

    @property
    def captured_chunks(self) -> list[RetrievedChunk]:
        return list(self.chunks_by_id.values())


@dataclass
class SkippedConversationRagRetriever:
    queries: list[str] = field(default_factory=list)

    def retrieve(self, query: str) -> RagRetrievalOutcome:
        return RagRetrievalOutcome(retrieval_method="skipped")
