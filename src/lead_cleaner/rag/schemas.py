"""
RAG schemas for knowledge base document types.

This module will define Pydantic models for:
- RawNotionPage
- KnowledgeDocument
- KnowledgeChunk
- RetrievedChunk
"""

# ─── Pydantic models will be added in subsequent commits ───
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lead_cleaner.schemas.policy import CustomerKind, Destination


RetrievalTopic = Literal[
    "pricing",
    "payment_policy",
    "travel_permit",
    "family_travel",
    "cultural_experience",
    "trip_duration",
    "flexible_pacing",
    "private_custom",
    "availability",
    "partnership",
]


class RetrievalIntent(BaseModel):
    """Deterministic, retrieval-only facts derived from a cleaned lead."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_kind: CustomerKind
    destinations: list[Destination] = Field(default_factory=list, max_length=10)
    group_size: int | None = Field(default=None, ge=1, le=10000)
    topic_codes: list[RetrievalTopic] = Field(default_factory=list, max_length=10)
    language: str = Field(default="unknown", min_length=2, max_length=30)


class RawNotionPage(BaseModel):
    notion_page_id: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)
    raw_blocks: list[dict[str, Any]]
    last_edited_time: str = Field(min_length=1)


class KnowledgeDocument(BaseModel):
    source_type: Literal["notion_page"]
    notion_page_id: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    source_path: str = Field(min_length=1)

    doc_type: Literal["product", "destination", "pricing", "faq"]
    region: Literal["western_sichuan", "tibet", "yunnan", "general"]
    product_name: str | None = None
    status: Literal["Active", "Draft", "Archived"]
    priority: Literal["P0", "P1", "P2"]
    tags: list[str]

    last_edited_time: str = Field(min_length=1)
    text: str = Field(min_length=1)


class KnowledgeChunk(BaseModel):
    chunk_id: str = Field(min_length=1)
    source_type: Literal["notion_page"]
    notion_page_id: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    doc_type: Literal["product", "destination", "pricing", "faq"]
    region: Literal["western_sichuan", "tibet", "yunnan", "general"]
    product_name: str | None = None
    section: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    chunk_strategy: Literal["heading_section"] = "heading_section"
    text: str = Field(min_length=1)
    last_edited_time: str = Field(min_length=1)


class RetrievedChunk(BaseModel):
    chunk_id: str = Field(min_length=1)
    source_type: Literal["notion_page"]
    notion_page_id: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    doc_type: Literal["product", "destination", "pricing", "faq"]
    region: Literal["western_sichuan", "tibet", "yunnan", "general"]
    product_name: str | None = None
    section: str = Field(min_length=1)
    text: str = Field(min_length=1)
    score: float
    rank: int = Field(ge=1)
    retrieval_source: Literal["bm25", "dense", "fusion", "rerank"]
