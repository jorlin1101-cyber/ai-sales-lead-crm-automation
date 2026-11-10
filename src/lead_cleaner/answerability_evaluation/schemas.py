"""Strict, evaluation-only contracts for the P0-02 frozen answerability suite."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from lead_cleaner.rag.schemas import KnowledgeChunk

Answerability = Literal["answerable", "partial", "unanswerable"]
Reason = Literal[
    "missing_customer_information",
    "missing_static_knowledge",
    "requires_live_supply",
    "conflicting_evidence",
    "expired_evidence",
    "unverified_validity",
]


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRef(StrictRecord):
    chunk_id: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_interval(self) -> Self:
        if self.start >= self.end:
            raise ValueError("evidence interval must have start < end")
        return self


class CustomerFact(StrictRecord):
    key: str = Field(min_length=1)
    value: str = Field(min_length=1)
    source_turn_id: str = Field(pattern=r"^T[1-9][0-9]*$")


class ExpectedFact(CustomerFact):
    statuses: list[Literal["customer_confirmed", "human_confirmed"]] = Field(
        default=["customer_confirmed", "human_confirmed"], min_length=1
    )


class Facet(StrictRecord):
    facet_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)
    required: StrictBool = True
    answerable: StrictBool
    reasons: list[Reason] = Field(default_factory=list)
    support_groups: list[list[str]] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    required_customer_fields: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    allowed_expressions: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def support_contract(self) -> Self:
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("duplicate no-answer reason")
        if self.answerable and (self.reasons or not self.support_groups):
            raise ValueError("answerable facet requires support groups and no blocking reason")
        if not self.answerable and (not self.reasons or self.support_groups):
            raise ValueError("unanswerable facet requires reasons and no usable support group")
        groups = [tuple(sorted(group)) for group in self.support_groups]
        if any(not group or len(group) != len(set(group)) for group in self.support_groups):
            raise ValueError("support groups must be nonempty and contain unique chunk IDs")
        if len(groups) != len(set(groups)):
            raise ValueError("duplicate support group")
        refs = [ref.chunk_id for ref in self.evidence_refs]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate facet evidence reference")
        if not {item for group in self.support_groups for item in group} <= set(refs):
            raise ValueError("every support member needs an exact evidence reference")
        if len(self.required_customer_fields) != len(set(self.required_customer_fields)):
            raise ValueError("duplicate required customer field")
        if "missing_customer_information" in self.reasons and not self.required_customer_fields:
            raise ValueError("missing customer information must identify required fields")
        return self


class Turn(StrictRecord):
    turn_id: str = Field(pattern=r"^T[1-9][0-9]*$")
    message: str = Field(min_length=1)
    evaluation_time: str
    business_date: str | None = None
    visible_turn_ids: list[str] = Field(default_factory=list)
    customer_facts: list[CustomerFact] = Field(default_factory=list)
    answerability: Answerability
    facets: list[Facet] = Field(min_length=1)
    judgments: dict[str, int]
    expected_facts: list[ExpectedFact] = Field(default_factory=list)
    expected_state: str | None = None
    expected_action: Literal["answer", "partial", "clarify"]
    expected_followup_fields: list[str] = Field(default_factory=list)
    forbidden_followup_fields: list[str] = Field(default_factory=list)

    @field_validator("evaluation_time")
    @classmethod
    def timezone_required(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("evaluation_time must contain an explicit timezone")
        return value

    @field_validator("business_date")
    @classmethod
    def date_only(cls, value: str | None) -> str | None:
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError("business_date must be an ISO date")
        return value

    @field_validator("judgments", mode="before")
    @classmethod
    def strict_grades(cls, value: Any) -> Any:
        if not isinstance(value, dict) or any(
            not isinstance(key, str) or not key or type(grade) is not int or grade not in range(4)
            for key, grade in value.items()
        ):
            raise ValueError("judgments require explicit integer grades 0 through 3")
        return value

    @model_validator(mode="after")
    def facet_state(self) -> Self:
        identifiers = [facet.facet_id for facet in self.facets]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate facet ID")
        required = [facet for facet in self.facets if facet.required]
        if not required:
            raise ValueError("a turn must have at least one required facet")
        count = sum(facet.answerable for facet in required)
        computed = (
            "answerable" if count == len(required) else "partial" if count else "unanswerable"
        )
        if computed != self.answerability:
            raise ValueError("answerability differs from required facets")
        action = {"answerable": "answer", "partial": "partial", "unanswerable": "clarify"}
        if self.expected_action != action[self.answerability]:
            raise ValueError("expected action differs from answerability")
        for facts in (self.customer_facts, self.expected_facts):
            if len({item.key for item in facts}) != len(facts):
                raise ValueError("each turn may declare only one current value per fact")
        if set(self.expected_followup_fields) & set(self.forbidden_followup_fields):
            raise ValueError("a follow-up field cannot be both required and forbidden")
        return self


class ReviewEvidence(StrictRecord):
    reviewer: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)

    @field_validator("reviewed_at")
    @classmethod
    def reviewed_timezone(cls, value: str) -> str:
        return Turn.timezone_required(value)


class Case(StrictRecord):
    case_id: str = Field(pattern=r"^AB[0-9]{2}$")
    case_version: int = Field(default=1, ge=1, strict=True)
    language: Literal["zh", "en", "mixed"]
    source: Literal["synthetic"] = "synthetic"
    suite_role: Literal["regression"] = "regression"
    exposure_status: Literal["visible"] = "visible"
    snapshot_id: str = Field(min_length=1)
    review_status: Literal["draft", "reviewed"] = "draft"
    review_evidence: list[ReviewEvidence] = Field(default_factory=list)
    turns: list[Turn] = Field(min_length=1)

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if self.review_status == "reviewed" and not self.review_evidence:
            raise ValueError("reviewed cases require explicit human review evidence")
        previous: list[str] = []
        previous_time: datetime | None = None
        for index, turn in enumerate(self.turns, 1):
            if turn.turn_id != f"T{index}" or turn.visible_turn_ids != previous:
                raise ValueError(
                    "turn IDs and visible history must follow exact chronological order"
                )
            current_time = datetime.fromisoformat(turn.evaluation_time)
            if previous_time is not None and current_time < previous_time:
                raise ValueError("evaluation time moved backwards")
            for fact in [*turn.customer_facts, *turn.expected_facts]:
                if fact.source_turn_id not in [*previous, turn.turn_id]:
                    raise ValueError("fact references a future or nonexistent turn")
            previous.append(turn.turn_id)
            previous_time = current_time
        return self


class EvaluationKnowledgeChunk(KnowledgeChunk):
    model_config = ConfigDict(extra="forbid")


class SnapshotChunk(StrictRecord):
    chunk: EvaluationKnowledgeChunk
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    valid_from: str | None = None
    valid_to: str | None = None
    validity_basis: Literal["evaluation_time", "business_date"] = "evaluation_time"
    conflict_key: str | None = None
    conflict_value: str | None = None

    @field_validator("valid_from", "valid_to")
    @classmethod
    def iso_date(cls, value: str | None) -> str | None:
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError("validity boundary must be an ISO date")
        return value

    @model_validator(mode="after")
    def validity_interval(self) -> Self:
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("valid_from must not be after valid_to")
        if bool(self.conflict_key) != bool(self.conflict_value):
            raise ValueError("conflict identity and value must be provided together")
        return self


class Snapshot(StrictRecord):
    snapshot_id: str = Field(min_length=1)
    synthetic: Literal[True] = True
    chunks: list[SnapshotChunk] = Field(min_length=1)
    review_scope: str = Field(min_length=1)


class CaseBundle(StrictRecord):
    schema_version: Literal["answerability-cases.v1"]
    protocol_id: Literal["p0-02.v1"]
    dataset_version: Literal["p0-02-cases.v1"]
    cases: list[Case] = Field(min_length=1)


class KnowledgeBundle(StrictRecord):
    schema_version: Literal["answerability-knowledge.v1"]
    snapshots: dict[str, Snapshot]


# V2 is explicit: loading a V1 document never supplies these defaults retroactively.
CorpusOrigin = Literal["original_handbook", "synthetic_fixture"]
EvaluationGroup = Literal["handbook", "synthetic_special"]


class FacetV2(Facet):
    policy_conflict_ids: list[str] = Field(default_factory=list)


class TurnV2(Turn):
    message_zh: str = Field(min_length=1)
    facets: list[FacetV2] = Field(min_length=1)  # type: ignore[assignment]


class CaseV2(Case):
    case_version: Literal[2]
    scenario_origin: Literal["synthetic_question"]
    corpus_origin: CorpusOrigin
    evaluation_group: EvaluationGroup
    turns: list[TurnV2] = Field(min_length=1)  # type: ignore[assignment]

    @model_validator(mode="after")
    def origin_agrees_with_group(self) -> Self:
        expected = {"handbook": "original_handbook", "synthetic_special": "synthetic_fixture"}
        if self.corpus_origin != expected[self.evaluation_group]:
            raise ValueError("case knowledge origin disagrees with evaluation group")
        return self


class ConflictEvidence(EvidenceRef):
    claim_value: str = Field(min_length=1)


class PolicyConflict(StrictRecord):
    conflict_id: str = Field(min_length=1)
    facet_id: str = Field(min_length=1)
    status: Literal["unresolved"]
    rationale: str = Field(min_length=1)
    evidence: list[ConflictEvidence] = Field(min_length=2)


class SnapshotV2(Snapshot):
    corpus_origin: CorpusOrigin
    source_manifest_id: str | None
    construction_purpose: str | None
    policy_conflicts: list[PolicyConflict] = Field(default_factory=list)

    @model_validator(mode="after")
    def explicit_source(self) -> Self:
        if self.corpus_origin == "original_handbook":
            if not self.source_manifest_id or self.construction_purpose is not None:
                raise ValueError("handbook requires its manifest and no fabricated construction")
        elif self.source_manifest_id is not None or not self.construction_purpose:
            raise ValueError("special snapshot requires its explicit construction purpose")
        return self


class CaseBundleV2(StrictRecord):
    schema_version: Literal["answerability-cases.v2"]
    protocol_id: Literal["p0-02.v2"]
    dataset_version: Literal["p0-02-cases.v2"]
    cases: list[CaseV2] = Field(min_length=1)


class KnowledgeBundleV2(StrictRecord):
    schema_version: Literal["answerability-knowledge.v2"]
    snapshots: dict[str, SnapshotV2]


class SourceFile(StrictRecord):
    lf_normalized_file_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_json_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ChunkSource(StrictRecord):
    chunk_id: str = Field(min_length=1)
    notion_page_id: str = Field(min_length=1)
    source_file: Literal["data/knowledge_snapshot/knowledge_chunks.json"]
    source_index: int = Field(ge=0, strict=True)
    exact_chunk_text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_file: Literal["data/knowledge_snapshot/notion_pages.json"]
    page_index: int = Field(ge=0, strict=True)
    page_text_start: int = Field(ge=0, strict=True)
    page_text_end: int = Field(gt=0, strict=True)
    page_quote: str = Field(min_length=1)


class SourceManifest(StrictRecord):
    schema_version: Literal["answerability-source-manifest.v2"]
    manifest_id: Literal["original-handbook.v2"]
    legacy_fact_probe_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_migration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    files: dict[str, SourceFile]
    page_count: Literal[8]
    chunk_count: Literal[47]
    chunk_order: list[str] = Field(min_length=47, max_length=47)
    chunks: list[ChunkSource] = Field(min_length=47, max_length=47)
