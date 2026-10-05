"""Read and cross-check frozen synthetic cases without running product code."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .schemas import CaseBundle, KnowledgeBundle, SnapshotChunk, Turn


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _reference_date(chunk: SnapshotChunk, turn: Turn) -> date | None:
    if chunk.validity_basis == "business_date":
        return date.fromisoformat(turn.business_date) if turn.business_date else None
    return datetime.fromisoformat(turn.evaluation_time).date()


def _valid(chunk: SnapshotChunk, turn: Turn) -> bool:
    point = _reference_date(chunk, turn)
    if point is None:
        return False
    return not (
        chunk.valid_from
        and point < date.fromisoformat(chunk.valid_from)
        or chunk.valid_to
        and point > date.fromisoformat(chunk.valid_to)
    )


def _expired(chunk: SnapshotChunk, turn: Turn) -> bool:
    point = _reference_date(chunk, turn)
    return bool(chunk.valid_to and point is not None and date.fromisoformat(chunk.valid_to) < point)


def validate_dataset(
    cases_payload: dict[str, Any], knowledge_payload: dict[str, Any]
) -> dict[str, Any]:
    cases = CaseBundle.model_validate(cases_payload)
    knowledge = KnowledgeBundle.model_validate(knowledge_payload)
    identifiers = [case.case_id for case in cases.cases]
    expected = {f"AB{index:02d}" for index in range(1, 25)}
    if len(identifiers) != 24 or set(identifiers) != expected:
        raise ValueError("p0-02.v1 requires exactly AB01 through AB24")
    if Counter(case.language for case in cases.cases) != {"zh": 10, "en": 10, "mixed": 4}:
        raise ValueError("p0-02.v1 requires 10 zh, 10 en and 4 mixed scenarios")
    if any(len(case.turns) != (1 if int(case.case_id[2:]) <= 18 else 3) for case in cases.cases):
        raise ValueError("the first 18 cases must be single-turn and the final 6 three-turn")
    if Counter(
        case.turns[0].answerability for case in cases.cases if int(case.case_id[2:]) <= 18
    ) != {"answerable": 6, "partial": 6, "unanswerable": 6}:
        raise ValueError("single-turn cases must contain six cases of each answerability state")
    all_reasons: set[str] = set()
    for key, snapshot in knowledge.snapshots.items():
        if key != snapshot.snapshot_id:
            raise ValueError("snapshot key differs from its identity")
        chunk_ids = [item.chunk.chunk_id for item in snapshot.chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("snapshot contains duplicate chunk IDs")
        for item in snapshot.chunks:
            if item.sha256 != text_hash(item.chunk.text):
                raise ValueError("knowledge text hash differs from its exact UTF-8 content")
    for case in cases.cases:
        if case.snapshot_id not in knowledge.snapshots:
            raise ValueError("case references an unknown snapshot")
        chunks = {
            item.chunk.chunk_id: item for item in knowledge.snapshots[case.snapshot_id].chunks
        }
        for turn in case.turns:
            empty_unanswerable = turn.answerability == "unanswerable" and not turn.judgments
            if not empty_unanswerable and set(turn.judgments) != set(chunks):
                raise ValueError(
                    "applicable IDCG requires explicit grades for the complete snapshot"
                )
            current_fields = {item.key for item in turn.customer_facts}
            for facet in turn.facets:
                all_reasons.update(facet.reasons)
                refs = []
                for ref in facet.evidence_refs:
                    if ref.chunk_id not in chunks:
                        raise ValueError("evidence references an unknown chunk")
                    item = chunks[ref.chunk_id]
                    if ref.sha256 != item.sha256 or ref.end > len(item.chunk.text):
                        raise ValueError("evidence hash or character interval is invalid")
                    if item.chunk.text[ref.start : ref.end] != ref.quote:
                        raise ValueError("evidence quote differs from its exact character interval")
                    refs.append(item)
                for group in facet.support_groups:
                    if any(not _valid(chunks[identifier], turn) for identifier in group):
                        raise ValueError(
                            "support group contains inapplicable or unverified-date evidence"
                        )
                missing = set(facet.required_customer_fields) - current_fields
                if "missing_customer_information" in facet.reasons and not missing:
                    raise ValueError("missing-customer label has no missing required field")
                if facet.answerable and missing:
                    raise ValueError("answerable facet lacks required customer information")
                if "expired_evidence" in facet.reasons:
                    if not refs or any(not _expired(item, turn) for item in refs):
                        raise ValueError(
                            "expired label requires explicitly elapsed validity periods"
                        )
                if "unverified_validity" in facet.reasons and (
                    not refs
                    or not any(item.valid_from is None and item.valid_to is None for item in refs)
                ):
                    raise ValueError("unverified validity requires a referenced metadata gap")
                if "conflicting_evidence" in facet.reasons:
                    keys = {item.conflict_key for item in refs}
                    values = {item.conflict_value for item in refs}
                    if (
                        len(refs) < 2
                        or len(keys) != 1
                        or None in keys
                        or len(values) < 2
                        or any(not _valid(item, turn) for item in refs)
                    ):
                        raise ValueError(
                            "conflict needs distinct applicable values for the same claim"
                        )
    expected_reasons = {
        "missing_customer_information",
        "missing_static_knowledge",
        "requires_live_supply",
        "conflicting_evidence",
        "expired_evidence",
        "unverified_validity",
    }
    if all_reasons != expected_reasons:
        raise ValueError("the full suite must cover all six no-answer reasons")
    return {
        "protocol_id": cases.protocol_id,
        "cases": [case.model_dump(mode="json") for case in cases.cases],
        "snapshots": {
            key: value.model_dump(mode="json") for key, value in knowledge.snapshots.items()
        },
    }


def load_dataset(root: Path) -> dict[str, Any]:
    """Load the complete 24-case protocol and fingerprint both original data files."""
    directory = Path(root) / "data" / "answerability_eval"
    case_bytes = (directory / "cases.json").read_bytes()
    knowledge_bytes = (directory / "knowledge.json").read_bytes()
    result = validate_dataset(json.loads(case_bytes), json.loads(knowledge_bytes))
    return result | {
        "dataset_hash": hashlib.sha256(case_bytes).hexdigest(),
        "knowledge_hash": hashlib.sha256(knowledge_bytes).hexdigest(),
    }
