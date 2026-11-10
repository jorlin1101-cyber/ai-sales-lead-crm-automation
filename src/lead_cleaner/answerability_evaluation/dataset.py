"""Read and cross-check frozen synthetic cases without running product code."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .registry import protocol_spec
from .schemas import (
    CaseBundle,
    CaseBundleV2,
    KnowledgeBundle,
    KnowledgeBundleV2,
    SnapshotChunk,
    SourceManifest,
    Turn,
)

SPECIAL_CASES = {"AB09", "AB10", "AB15", "AB16", "AB17", "AB23"}
SOURCE_FILES = (
    "data/knowledge_snapshot/notion_pages.json",
    "data/knowledge_snapshot/knowledge_chunks.json",
)


def canonical_hash(value: Any) -> str:
    return text_hash(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    )


def _source_manifest(
    root: Path, knowledge: KnowledgeBundleV2, payload: dict[str, Any]
) -> dict[str, Any]:
    manifest = SourceManifest.model_validate(payload)
    if set(manifest.files) != set(SOURCE_FILES):
        raise ValueError("source manifest must bind the two fixed handbook files")
    sources, checkout = {}, {}
    for name in SOURCE_FILES:
        location = (root / name).resolve()
        if not location.is_relative_to(root.resolve()):
            raise ValueError("handbook source escapes the requested repository")
        raw = location.read_bytes()
        value = json.loads(raw)
        binding = manifest.files[name]
        if (
            hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
            != binding.lf_normalized_file_hash
            or canonical_hash(value) != binding.canonical_json_hash
        ):
            raise ValueError("original handbook file differs from the frozen source manifest")
        sources[name], checkout[name] = value, hashlib.sha256(raw).hexdigest()
    pages, original = (sources[name] for name in SOURCE_FILES)
    if len(pages) != 8 or len(original) != 47:
        raise ValueError("source manifest requires all 8 pages and 47 original chunks")
    ids = [chunk["chunk_id"] for chunk in original]
    if len(set(ids)) != 47 or manifest.chunk_order != ids:
        raise ValueError("handbook source order differs from all 47 original chunks")
    handbook = [s for s in knowledge.snapshots.values() if s.corpus_origin == "original_handbook"]
    if len(handbook) != 1 or handbook[0].source_manifest_id != manifest.manifest_id:
        raise ValueError("exactly one original handbook snapshot must bind the source manifest")
    snapshot = handbook[0]
    if [item.chunk.model_dump(mode="json") for item in snapshot.chunks] != original:
        raise ValueError(
            "handbook snapshot must preserve every production field and original order"
        )
    for item in snapshot.chunks:
        if (
            item.valid_from is not None
            or item.valid_to is not None
            or item.conflict_key is not None
            or item.conflict_value is not None
            or item.validity_basis != "evaluation_time"
        ):
            raise ValueError(
                "handbook chunks cannot invent whole-chunk validity or conflict policies"
            )
    for index, (record, chunk) in enumerate(zip(manifest.chunks, original, strict=True)):
        if (
            record.source_index != index
            or record.chunk_id != chunk["chunk_id"]
            or record.notion_page_id != chunk["notion_page_id"]
            or record.exact_chunk_text_hash != text_hash(chunk["text"])
            or record.production_record_hash != canonical_hash(chunk)
        ):
            raise ValueError("source manifest chunk identity, text or production record differs")
        if record.page_index >= len(pages):
            raise ValueError("source page index is outside the frozen handbook")
        page = pages[record.page_index]
        if any(
            page[field] != chunk[field]
            for field in (
                "notion_page_id",
                "source_title",
                "source_path",
                "doc_type",
                "region",
                "product_name",
                "last_edited_time",
            )
        ):
            raise ValueError("source chunk metadata differs from its original handbook page")
        if (
            not 0 <= record.page_text_start < record.page_text_end <= len(page["text"])
            or page["text"][record.page_text_start : record.page_text_end] != record.page_quote
            or chunk["text"] != "# " + page["source_title"] + "\n" + record.page_quote
        ):
            raise ValueError("source manifest page quote is not the exact original chunk body")
    return {
        "source_manifest": manifest.model_dump(mode="json"),
        "source_manifest_hash": canonical_hash(manifest.model_dump(mode="json")),
        "source_checkout_hashes": checkout,
    }


def _validate_migration(root: Path, cases: dict[str, Any], manifest: dict[str, Any]) -> None:
    directory = root / "data/answerability_eval/v2"
    probe = json.loads((directory / "legacy_fact_probe.json").read_bytes())
    migration = json.loads((directory / "case_migration.json").read_bytes())
    if (
        canonical_hash(probe) != manifest["legacy_fact_probe_hash"]
        or canonical_hash(migration) != manifest["case_migration_hash"]
    ):
        raise ValueError("v2 legacy probe or migration mapping differs from its manifest")
    previous = json.loads((root / "data/answerability_eval/cases.json").read_bytes())
    old = {case["case_id"]: case for case in previous["cases"]}
    original = old["AB22"]
    if (
        probe.get("schema_version") != "answerability-legacy-fact-probe.v2"
        or probe.get("source_protocol_id") != "p0-02.v1"
        or probe.get("case_id") != "AB22"
        or probe.get("source_cases_file") != "data/answerability_eval/cases.json"
        or probe.get("status") != "diagnostic_only"
        or probe.get("source_case_hash") != canonical_hash(original)
        or probe.get("messages") != [turn["message"] for turn in original["turns"]]
        or probe.get("expected_facts_by_turn")
        != {turn["turn_id"]: turn["expected_facts"] for turn in original["turns"]}
    ):
        raise ValueError(
            "legacy fact probe must preserve the exact original v1 AB22 inputs and facts"
        )
    if (
        migration.get("schema_version") != "answerability-case-migration.v2"
        or migration.get("from_protocol") != "p0-02.v1"
        or migration.get("to_protocol") != "p0-02.v2"
        or migration.get("source_cases_hash") != canonical_hash(previous)
    ):
        raise ValueError("migration must bind the original v1 case bundle")
    current = {case["case_id"]: case for case in cases["cases"]}
    entries = migration.get("cases", [])
    if len(entries) != 24 or {entry["case_id"] for entry in entries} != set(current):
        raise ValueError("migration requires every v2 case exactly once")
    for entry in entries:
        left, right = old[entry["case_id"]], current[entry["case_id"]]
        changed = [
            turn["turn_id"]
            for turn, earlier in zip(right["turns"], left["turns"], strict=True)
            if turn["message"] != earlier["message"]
        ]
        expected = {
            "case_id": right["case_id"],
            "evaluation_group": right["evaluation_group"],
            "previous_snapshot": left["snapshot_id"],
            "current_snapshot": right["snapshot_id"],
            "source_case_hash": canonical_hash(left),
            "current_case_hash": canonical_hash(right),
            "changed_messages": changed,
            "comparison_policy": "new_protocol_not_score_comparable",
        }
        if entry != expected:
            raise ValueError("case migration mapping does not match its actual v1/v2 cases")
    revised = current["AB22"]["turns"]
    if revised[1]["message"] != original["turns"][1]["message"] or [
        turn["expected_facts"] for turn in revised
    ] != [turn["expected_facts"] for turn in original["turns"]]:
        raise ValueError(
            "v2 must retain AB22's unchanged negative correction and all expected facts"
        )


def _validate_v2_groups(cases: CaseBundleV2, knowledge: KnowledgeBundleV2) -> dict[str, Any]:
    groups = {}
    used = {case.snapshot_id for case in cases.cases}
    if used != set(knowledge.snapshots):
        raise ValueError("v2 cannot contain unused or missing knowledge snapshots")
    for case in cases.cases:
        group = "synthetic_special" if case.case_id in SPECIAL_CASES else "handbook"
        if (
            case.evaluation_group != group
            or case.corpus_origin != knowledge.snapshots[case.snapshot_id].corpus_origin
        ):
            raise ValueError("case group or origin differs from its frozen source assignment")
    for name, expected_counts, required_reasons in (
        (
            "handbook",
            (18, 13, 5, 28, 39),
            {
                "missing_customer_information",
                "missing_static_knowledge",
                "requires_live_supply",
                "conflicting_evidence",
            },
        ),
        (
            "synthetic_special",
            (6, 5, 1, 8, 15),
            {
                "missing_customer_information",
                "expired_evidence",
                "conflicting_evidence",
                "unverified_validity",
            },
        ),
    ):
        selected = [case for case in cases.cases if case.evaluation_group == name]
        single = sum(len(case.turns) == 1 for case in selected)
        multi = sum(len(case.turns) == 3 for case in selected)
        turns = [turn for case in selected for turn in case.turns]
        if (len(selected), single, multi, len(turns), single * 3) != expected_counts:
            raise ValueError("v2 group scenario, turn or retrieval coverage differs")
        reasons = {
            reason
            for turn in turns
            for facet in turn.facets
            if facet.required
            for reason in facet.reasons
        }
        states = {turn.answerability for turn in turns}
        if not required_reasons <= reasons or states != {"answerable", "partial", "unanswerable"}:
            raise ValueError(
                "each v2 group must independently cover its required states and reasons"
            )
        if name == "synthetic_special":
            multi_case = next(case for case in selected if len(case.turns) == 3)
            if not any(
                f.required_customer_fields and f.answerable
                for t in multi_case.turns
                for f in t.facets
            ):
                raise ValueError(
                    "special multi-turn case must include a valid conditional contrast"
                )
        groups[name] = {
            "case_ids": [case.case_id for case in selected],
            "scenario_count": len(selected),
            "turn_count": len(turns),
            "retrieval_unit_count": single * 3,
            "answerability_states": sorted(states),
            "reasons": sorted(reasons),
        }
    return groups


def _validate_policy_conflicts(knowledge: KnowledgeBundleV2) -> None:
    for snapshot in knowledge.snapshots.values():
        ids = [conflict.conflict_id for conflict in snapshot.policy_conflicts]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate policy conflict identity")
        chunks = {item.chunk.chunk_id: item for item in snapshot.chunks}
        for conflict in snapshot.policy_conflicts:
            if len({ref.claim_value for ref in conflict.evidence}) < 2:
                raise ValueError("policy conflict needs different statement values")
            if len({ref.chunk_id for ref in conflict.evidence}) != len(conflict.evidence):
                raise ValueError("policy conflict needs distinct source chunks")
            for ref in conflict.evidence:
                item = chunks.get(ref.chunk_id)
                if (
                    item is None
                    or ref.sha256 != item.sha256
                    or ref.end > len(item.chunk.text)
                    or item.chunk.text[ref.start : ref.end] != ref.quote
                ):
                    raise ValueError("policy conflict must bind precise original statement spans")


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
    cases_payload: dict[str, Any],
    knowledge_payload: dict[str, Any],
    *,
    root: Path | None = None,
    source_manifest_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = protocol_spec(cases_payload.get("protocol_id", ""))
    version2 = spec["protocol_id"] == "p0-02.v2"
    cases = (
        CaseBundleV2.model_validate(cases_payload)
        if version2
        else CaseBundle.model_validate(cases_payload)
    )
    knowledge = (
        KnowledgeBundleV2.model_validate(knowledge_payload)
        if version2
        else KnowledgeBundle.model_validate(knowledge_payload)
    )
    source_info = {}
    if isinstance(cases, CaseBundleV2) and isinstance(knowledge, KnowledgeBundleV2):
        source_root = (root or Path(__file__).resolve().parents[3]).resolve()
        payload = (
            source_manifest_payload
            if source_manifest_payload is not None
            else json.loads(
                (source_root / spec["data_directory"] / "source_manifest.json").read_bytes()
            )
        )
        source_info = _source_manifest(source_root, knowledge, payload)
        source_info["groups"] = _validate_v2_groups(cases, knowledge)
        _validate_policy_conflicts(knowledge)
    identifiers = [case.case_id for case in cases.cases]
    expected = {f"AB{index:02d}" for index in range(1, 25)}
    if len(identifiers) != 24 or set(identifiers) != expected:
        raise ValueError("answerability suite requires exactly AB01 through AB24")
    if Counter(case.language for case in cases.cases) != {"zh": 10, "en": 10, "mixed": 4}:
        raise ValueError("answerability suite requires 10 zh, 10 en and 4 mixed scenarios")
    if any(len(case.turns) != (1 if int(case.case_id[2:]) <= 18 else 3) for case in cases.cases):
        raise ValueError("the first 18 cases must be single-turn and the final 6 three-turn")
    if not version2 and Counter(
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
                policy_ids = getattr(facet, "policy_conflict_ids", [])
                if policy_ids:
                    policies = {
                        p.conflict_id: p
                        for p in getattr(
                            knowledge.snapshots[case.snapshot_id], "policy_conflicts", []
                        )
                    }
                    if (
                        facet.answerable
                        or "conflicting_evidence" not in facet.reasons
                        or len(policy_ids) != len(set(policy_ids))
                        or not set(policy_ids) <= set(policies)
                    ):
                        raise ValueError("facet references invalid policy conflicts")
                    facet_refs = {
                        (ref.chunk_id, ref.sha256, ref.start, ref.end, ref.quote)
                        for ref in facet.evidence_refs
                    }
                    for identifier in policy_ids:
                        policy = policies[identifier]
                        if (
                            policy.facet_id != facet.facet_id
                            or not {
                                (ref.chunk_id, ref.sha256, ref.start, ref.end, ref.quote)
                                for ref in policy.evidence
                            }
                            <= facet_refs
                        ):
                            raise ValueError(
                                "conflicting facet must retain all precise policy statements"
                            )
                if "conflicting_evidence" in facet.reasons and not policy_ids:
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
    if version2:
        _validate_migration(source_root, cases_payload, source_info["source_manifest"])
    return {
        **source_info,
        "protocol_id": cases.protocol_id,
        "cases": [case.model_dump(mode="json") for case in cases.cases],
        "snapshots": {
            key: value.model_dump(mode="json") for key, value in knowledge.snapshots.items()
        },
    }


def load_dataset(root: Path, protocol_id: str = "p0-02.v1") -> dict[str, Any]:
    """Load the complete 24-case protocol and fingerprint both original data files."""
    directory = Path(root) / protocol_spec(protocol_id)["data_directory"]
    case_bytes = (directory / "cases.json").read_bytes()
    knowledge_bytes = (directory / "knowledge.json").read_bytes()
    payload = json.loads(case_bytes)
    if payload.get("protocol_id") != protocol_id:
        raise ValueError("dataset file belongs to a different requested protocol")
    result = validate_dataset(payload, json.loads(knowledge_bytes), root=Path(root))
    return result | {
        "dataset_hash": hashlib.sha256(case_bytes).hexdigest(),
        "knowledge_hash": hashlib.sha256(knowledge_bytes).hexdigest(),
    }
