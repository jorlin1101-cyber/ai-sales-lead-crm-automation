from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lead_cleaner.schemas.lead import KnowledgeSource, LeadProcessingResult


ConversationChannel = Literal[
    "email",
    "web_chat",
    "social_dm",
    "wechat",
    "sms",
    "api",
    "manual",
]
ConversationState = Literal[
    "new",
    "waiting_customer",
    "ready_for_review",
    "needs_human_review",
    "closed",
    "do_not_contact",
]
FactStatus = Literal[
    "inferred",
    "customer_confirmed",
    "human_confirmed",
    "conflicted",
    "pending",
]
TurnIdempotencyStatus = Literal["created", "duplicate"]


class ConversationMessageRequest(BaseModel):
    """Canonical inbound message after a channel adapter has normalized it."""

    model_config = ConfigDict(extra="forbid")

    channel: ConversationChannel
    source: str = Field(default="unknown", min_length=1, max_length=100)
    external_conversation_id: str = Field(min_length=1, max_length=200)
    external_message_id: str = Field(min_length=1, max_length=300)
    in_reply_to: str | None = Field(default=None, max_length=300)
    account_id: str = Field(default="default", min_length=1, max_length=100)
    sender_name: str | None = Field(default=None, max_length=200)
    sender_email: str | None = Field(default=None, max_length=320)
    company_name: str | None = Field(default=None, max_length=300)
    subject: str | None = Field(default=None, max_length=500)
    message: str = Field(min_length=1, max_length=5000)
    source_authorized: Literal[True]


class ConversationFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=500)
    status: FactStatus
    confidence: float = Field(ge=0, le=1)
    source_message_id: str = Field(min_length=1, max_length=300)


class ProductRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str
    display_name: str
    fit_status: Literal["candidate", "needs_customization"]
    reasons: list[str] = Field(default_factory=list, max_length=5)
    manual_summary: list[str] = Field(default_factory=list, max_length=4)
    adjustments: list[str] = Field(default_factory=list, max_length=5)
    source_ids: list[str] = Field(default_factory=list, max_length=3)


class ReplyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1, max_length=100)
    channel: ConversationChannel
    conversation_id: str = Field(min_length=1, max_length=100)
    turn_number: int = Field(ge=1)
    status: Literal[
        "needs_human_review", "ready_for_review", "approved", "rejected", "suppressed", "sent"
    ]
    subject: str | None = Field(default=None, max_length=500)
    body_text: str = Field(max_length=5000)
    body_html: str | None = None
    display_text: str = Field(max_length=5000)
    open_questions: list[str] = Field(default_factory=list, max_length=10)
    source_ids: list[str] = Field(default_factory=list, max_length=3)
    generation_method: Literal["context_template", "rag_grounded_template", "llm_grounded"] = (
        "context_template"
    )
    answer_intents: list[str] = Field(default_factory=list, max_length=5)
    policy_version: str = Field(min_length=1, max_length=50)
    draft_version: int = Field(default=1, ge=1)
    evidence: list[dict[str, str]] = Field(default_factory=list, max_length=3)
    internal_note: str | None = None
    recommended_products: list[ProductRecommendation] = Field(default_factory=list, max_length=2)


class ConversationRetrievalTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["required", "skipped", "blocked"]
    reason: str = Field(min_length=1, max_length=100)
    queries: list[str] = Field(default_factory=list, max_length=8)
    retrieval_method: str = Field(min_length=1, max_length=50)
    sources: list[KnowledgeSource] = Field(default_factory=list, max_length=3)


class ConversationTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1, max_length=100)
    turn_number: int = Field(ge=1)
    state: ConversationState
    idempotency_status: TurnIdempotencyStatus
    current_analysis: LeadProcessingResult
    confirmed_facts: list[ConversationFact] = Field(default_factory=list, max_length=20)
    open_questions: list[str] = Field(default_factory=list, max_length=10)
    reply_draft: ReplyDraft
    retrieval: ConversationRetrievalTrace
    requires_human_review: bool
    message_score: int | None = None
    score_scope: Literal["conversation"] = "conversation"
    reply_language: Literal["zh", "en"] = "zh"
    llm_trace: dict[str, str] = Field(default_factory=dict)


class ConversationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    channel: ConversationChannel
    source: str
    state: ConversationState
    turn_number: int = Field(ge=0)
    context_summary: str
    updated_at: str


class ConversationTimelineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    direction: Literal["inbound", "outbound"]
    channel: ConversationChannel
    turn_number: int = Field(ge=1)
    subject: str | None = None
    text_preview: str
    created_at: str
    draft_status: str | None = None
    reply_text_preview: str | None = None
    source_count: int = Field(default=0, ge=0, le=3)
    text: str = ""
    reply_text: str | None = None
    processing_status: str = "processed"


class DraftReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    action: Literal["save", "approve", "reject", "record_sent"]
    body_text: str | None = Field(default=None, min_length=1, max_length=5000)
    # record_sent records a human action; this endpoint never sends a message.
    external_receipt: str | None = Field(default=None, min_length=1, max_length=300)


class DraftSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)
