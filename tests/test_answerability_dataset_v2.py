"""V2 source lineage, independent group coverage, and unchanged historical evidence."""

from copy import deepcopy
from collections import Counter
import hashlib
import json
from pathlib import Path

import pytest

from lead_cleaner.answerability_evaluation.dataset import (
    SPECIAL_CASES,
    canonical_hash,
    load_dataset,
    validate_dataset,
)
from lead_cleaner.answerability_evaluation.schemas import CaseBundleV2, KnowledgeBundleV2

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "data/answerability_eval/v2"


@pytest.fixture
def documents(tmp_path):
    names = [
        "data/knowledge_snapshot/notion_pages.json",
        "data/knowledge_snapshot/knowledge_chunks.json",
        "data/answerability_eval/cases.json",
        *["data/answerability_eval/v2/" + p.name for p in DIRECTORY.glob("*.json")],
    ]
    for name in names:
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    return {
        "root": tmp_path,
        "cases": json.loads((DIRECTORY / "cases.json").read_bytes()),
        "knowledge": json.loads((DIRECTORY / "knowledge.json").read_bytes()),
        "manifest": json.loads((DIRECTORY / "source_manifest.json").read_bytes()),
    }


def validate(documents):
    return validate_dataset(
        documents["cases"],
        documents["knowledge"],
        root=documents["root"],
        source_manifest_payload=documents["manifest"],
    )


def test_v1_unchanged_interface_and_v2_complete_separate_groups():
    old = load_dataset(ROOT)
    new = load_dataset(ROOT, "p0-02.v2")
    assert old["protocol_id"] == "p0-02.v1" and len(old["snapshots"]) == 7
    assert "source_manifest" not in old and "evaluation_group" not in old["cases"][0]
    assert len(new["cases"]) == 24 and sum(len(c["turns"]) for c in new["cases"]) == 36
    assert Counter(c["language"] for c in new["cases"]) == {"zh": 10, "en": 10, "mixed": 4}
    assert all(c["review_status"] == "draft" and not c["review_evidence"] for c in new["cases"])
    assert all(c["scenario_origin"] == "synthetic_question" for c in new["cases"])
    for group, counts in (("handbook", (18, 28, 39)), ("synthetic_special", (6, 8, 15))):
        stats = new["groups"][group]
        assert (
            stats["scenario_count"],
            stats["turn_count"],
            stats["retrieval_unit_count"],
        ) == counts
        assert stats["answerability_states"] == ["answerable", "partial", "unanswerable"]
    assert set(new["groups"]["synthetic_special"]["case_ids"]) == SPECIAL_CASES
    assert Counter(c["turns"][0]["answerability"] for c in new["cases"][:18]) != {
        "answerable": 6,
        "partial": 6,
        "unanswerable": 6,
    }


def test_all_47_production_records_and_order_are_exact_and_all_sources_trace():
    data = load_dataset(ROOT, "p0-02.v2")
    original = json.loads((ROOT / "data/knowledge_snapshot/knowledge_chunks.json").read_bytes())
    assert [c["chunk"] for c in data["snapshots"]["handbook"]["chunks"]] == original
    manifest = data["source_manifest"]
    assert data["source_manifest_hash"] == canonical_hash(manifest)
    assert len(manifest["chunks"]) == 47 and manifest["page_count"] == 8
    assert manifest["chunk_order"] == [c["chunk_id"] for c in original]
    assert any(c["doc_type"] == "product" for c in original)
    for c, binding in zip(original, manifest["chunks"], strict=True):
        assert binding["exact_chunk_text_hash"] == hashlib.sha256(c["text"].encode()).hexdigest()
        assert binding["production_record_hash"] == canonical_hash(c)


def test_actual_due_date_difference_is_span_scoped_and_does_not_invent_validity():
    data = load_dataset(ROOT, "p0-02.v2")
    handbook = data["snapshots"]["handbook"]
    assert all(c["conflict_key"] is None and c["valid_from"] is None for c in handbook["chunks"])
    conflict = handbook["policy_conflicts"][0]
    assert len(conflict["evidence"]) == 3
    assert {r["claim_value"] for r in conflict["evidence"]} == {
        "before_arrival",
        "before_departure",
    }
    case = next(c for c in data["cases"] if c["case_id"] == "AB11")
    deposit, deadline = case["turns"][0]["facets"]
    assert deposit["answerable"] and not deadline["answerable"]
    assert deadline["policy_conflict_ids"] == ["balance_deadline"]
    for ref in deposit["evidence_refs"]:
        assert not any(
            r["chunk_id"] == ref["chunk_id"]
            and max(r["start"], ref["start"]) < min(r["end"], ref["end"])
            for r in conflict["evidence"]
        )


def test_original_customer_correction_and_complete_diagnostic_input_are_preserved():
    old, new = (load_dataset(ROOT, version) for version in ("p0-02.v1", "p0-02.v2"))
    a, b = (next(c for c in d["cases"] if c["case_id"] == "AB22") for d in (old, new))
    assert a["turns"][1]["message"] == b["turns"][1]["message"]
    assert [t["expected_facts"] for t in a["turns"]] == [t["expected_facts"] for t in b["turns"]]
    probe = json.loads((DIRECTORY / "legacy_fact_probe.json").read_bytes())
    assert probe["messages"] == [t["message"] for t in a["turns"]]
    assert probe["status"] == "diagnostic_only"


def test_original_child_conditions_distinguish_customer_information_and_supply():
    data = load_dataset(ROOT, "p0-02.v2")
    turns = next(c for c in data["cases"] if c["case_id"] == "AB19")["turns"]
    assert [t["answerability"] for t in turns] == ["unanswerable", "answerable", "unanswerable"]
    assert set(turns[0]["expected_followup_fields"]) == {"child_age", "shares_room_with_parents"}
    assert {f["source_turn_id"] for f in turns[1]["customer_facts"]} == {"T2"}
    assert turns[2]["facets"][0]["reasons"] == ["requires_live_supply"]
    assert all("活动" not in t["message"] for t in turns)


@pytest.mark.parametrize(
    "mutation",
    [
        "deleted",
        "reordered",
        "doc_type",
        "text",
        "product_name",
        "invented_validity",
        "whole_chunk_conflict",
    ],
)
def test_handbook_cannot_be_cropped_relabelled_or_rewritten(documents, mutation):
    rows = documents["knowledge"]["snapshots"]["handbook"]["chunks"]
    if mutation == "deleted":
        rows.pop()
    elif mutation == "reordered":
        rows.reverse()
    elif mutation == "invented_validity":
        rows[0]["valid_from"] = "2026-10-01"
    elif mutation == "whole_chunk_conflict":
        rows[0].update(conflict_key="all", conflict_value="fake")
    elif mutation == "text":
        rows[0]["chunk"]["text"] += " New policy."
    else:
        rows[0]["chunk"][mutation] = "faq" if mutation == "doc_type" else "Other product"
    with pytest.raises(ValueError, match="handbook"):
        validate(documents)


@pytest.mark.parametrize(
    "mutation",
    [
        "file_hash",
        "json_hash",
        "missing_file",
        "order",
        "index",
        "identity",
        "record_hash",
        "text_hash",
        "page_index",
        "page_quote",
        "page_interval",
        "source_page_metadata",
    ],
)
def test_source_manifest_cannot_self_assert_false_lineage(documents, mutation):
    manifest = documents["manifest"]
    record = manifest["chunks"][0]
    file = manifest["files"]["data/knowledge_snapshot/notion_pages.json"]
    if mutation == "file_hash":
        file["lf_normalized_file_hash"] = "0" * 64
    elif mutation == "json_hash":
        file["canonical_json_hash"] = "0" * 64
    elif mutation == "missing_file":
        manifest["files"].pop("data/knowledge_snapshot/notion_pages.json")
    elif mutation == "order":
        manifest["chunk_order"].reverse()
    elif mutation == "index":
        record["source_index"] = 1
    elif mutation == "identity":
        record["notion_page_id"] = "different-page"
    elif mutation == "record_hash":
        record["production_record_hash"] = "0" * 64
    elif mutation == "text_hash":
        record["exact_chunk_text_hash"] = "0" * 64
    elif mutation == "page_index":
        record["page_index"] = 999
    elif mutation == "page_quote":
        record["page_quote"] += " forged"
    elif mutation == "page_interval":
        record["page_text_end"] += 1
    else:
        record["page_index"] = 1
    with pytest.raises(ValueError):
        validate(documents)


def test_source_file_changes_detected_but_checkout_line_endings_are_diagnostic(documents):
    expected = validate(documents)
    path = documents["root"] / "data/knowledge_snapshot/notion_pages.json"
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    alternate = validate(documents)
    assert expected["source_manifest_hash"] == alternate["source_manifest_hash"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="original handbook file differs"):
        validate(documents)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_group",
        "wrong_origin",
        "missing_origin",
        "fake_review",
        "missing_translation",
        "v1_schema",
        "unknown_snapshot",
        "unused_snapshot",
        "handbook_purpose",
        "special_missing_purpose",
        "wrong_manifest",
    ],
)
def test_v2_origin_review_and_version_contract_is_explicit(documents, mutation):
    case = documents["cases"]["cases"][0]
    knowledge = documents["knowledge"]
    if mutation == "wrong_group":
        case.update(evaluation_group="synthetic_special", corpus_origin="synthetic_fixture")
    elif mutation == "wrong_origin":
        case["corpus_origin"] = "synthetic_fixture"
    elif mutation == "missing_origin":
        case.pop("scenario_origin")
    elif mutation == "fake_review":
        case["review_status"] = "reviewed"
    elif mutation == "missing_translation":
        case["turns"][0].pop("message_zh")
    elif mutation == "v1_schema":
        knowledge["schema_version"] = "answerability-knowledge.v1"
    elif mutation == "unknown_snapshot":
        case["snapshot_id"] = "absent"
    elif mutation == "unused_snapshot":
        knowledge["snapshots"]["unused"] = deepcopy(knowledge["snapshots"]["special_expired"])
    elif mutation == "handbook_purpose":
        knowledge["snapshots"]["handbook"]["construction_purpose"] = "invented"
    elif mutation == "special_missing_purpose":
        knowledge["snapshots"]["special_expired"]["construction_purpose"] = None
    else:
        knowledge["snapshots"]["handbook"]["source_manifest_id"] = "different"
    with pytest.raises(ValueError):
        validate(documents)


def test_special_coverage_cannot_replace_handbook_payment_difference(documents):
    case = next(c for c in documents["cases"]["cases"] if c["case_id"] == "AB11")
    turn = case["turns"][0]
    turn["facets"][1]["required"] = False
    turn.update(answerability="answerable", expected_action="answer")
    with pytest.raises(ValueError, match="independently cover"):
        validate(documents)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "same_values",
        "same_chunk",
        "wrong_quote",
        "wrong_hash",
        "bad_end",
        "unknown_chunk",
        "missing_facet_ref",
        "wrong_facet",
        "unknown_policy",
    ],
)
def test_payment_conflict_requires_real_distinct_precise_statements(documents, mutation):
    conflict = documents["knowledge"]["snapshots"]["handbook"]["policy_conflicts"][0]
    facet = next(c for c in documents["cases"]["cases"] if c["case_id"] == "AB11")["turns"][0][
        "facets"
    ][1]
    if mutation == "duplicate":
        documents["knowledge"]["snapshots"]["handbook"]["policy_conflicts"].append(
            deepcopy(conflict)
        )
    elif mutation == "same_values":
        for ref in conflict["evidence"]:
            ref["claim_value"] = "before_arrival"
    elif mutation == "same_chunk":
        conflict["evidence"][1] = deepcopy(conflict["evidence"][0])
    elif mutation == "wrong_quote":
        conflict["evidence"][0]["quote"] += " altered"
    elif mutation == "wrong_hash":
        conflict["evidence"][0]["sha256"] = "0" * 64
    elif mutation == "bad_end":
        conflict["evidence"][0]["end"] += 99999
    elif mutation == "unknown_chunk":
        conflict["evidence"][0]["chunk_id"] = "absent"
    elif mutation == "missing_facet_ref":
        facet["evidence_refs"].pop()
    elif mutation == "wrong_facet":
        conflict["facet_id"] = "deposit"
    else:
        facet["policy_conflict_ids"] = ["absent"]
    with pytest.raises(ValueError, match="conflict"):
        validate(documents)


@pytest.mark.parametrize(
    "mutation",
    [
        "probe_hash",
        "migration_hash",
        "probe_message",
        "probe_facts",
        "probe_source_hash",
        "migration_missing",
        "migration_current",
        "migration_old",
        "original_changed",
    ],
)
def test_original_inputs_and_migration_cannot_be_rewritten(documents, mutation):
    base = documents["root"] / "data/answerability_eval/v2"
    manifest = documents["manifest"]
    probe = json.loads((base / "legacy_fact_probe.json").read_bytes())
    mapping = json.loads((base / "case_migration.json").read_bytes())
    if mutation == "probe_hash":
        manifest["legacy_fact_probe_hash"] = "0" * 64
    elif mutation == "migration_hash":
        manifest["case_migration_hash"] = "0" * 64
    elif mutation == "probe_message":
        probe["messages"][1] = "We are nine people."
    elif mutation == "probe_facts":
        probe["expected_facts_by_turn"]["T2"][0]["value"] = "8"
    elif mutation == "probe_source_hash":
        probe["source_case_hash"] = "0" * 64
    elif mutation == "migration_missing":
        mapping["cases"].pop()
    elif mutation == "migration_current":
        mapping["cases"][0]["current_case_hash"] = "0" * 64
    elif mutation == "migration_old":
        mapping["source_cases_hash"] = "0" * 64
    else:
        path = documents["root"] / "data/answerability_eval/cases.json"
        original = json.loads(path.read_bytes())
        original["cases"][21]["turns"][1]["message"] = "Changed correction"
        path.write_text(json.dumps(original), encoding="utf-8")
    (base / "legacy_fact_probe.json").write_text(json.dumps(probe), encoding="utf-8")
    (base / "case_migration.json").write_text(json.dumps(mapping), encoding="utf-8")
    if mutation != "probe_hash":
        manifest["legacy_fact_probe_hash"] = canonical_hash(probe)
    if mutation != "migration_hash":
        manifest["case_migration_hash"] = canonical_hash(mapping)
    with pytest.raises(ValueError, match="probe|migration"):
        validate(documents)


def test_mixed_payload_versions_and_arbitrary_protocols_are_rejected(documents):
    with pytest.raises(ValueError):
        load_dataset(ROOT, "../../v2")
    with pytest.raises(ValueError):
        CaseBundleV2.model_validate(
            json.loads((ROOT / "data/answerability_eval/cases.json").read_bytes())
        )
    with pytest.raises(ValueError):
        KnowledgeBundleV2.model_validate(
            json.loads((ROOT / "data/answerability_eval/knowledge.json").read_bytes())
        )
    path = documents["root"] / "data/answerability_eval/v2/cases.json"
    wrong = json.loads(path.read_bytes())
    wrong["protocol_id"] = "p0-02.v1"
    path.write_text(json.dumps(wrong), encoding="utf-8")
    with pytest.raises(ValueError, match="different requested protocol"):
        load_dataset(documents["root"], "p0-02.v2")
