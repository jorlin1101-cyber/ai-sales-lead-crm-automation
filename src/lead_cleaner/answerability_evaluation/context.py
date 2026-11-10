"""Fingerprint the actual local source and the independently versioned protocol."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lead_cleaner.answerability_evaluation.checks import expected_keys, expected_retrieval_keys
from lead_cleaner.answerability_evaluation.reports import content_hash, file_hash
from lead_cleaner.answerability_evaluation.registry import protocol_spec
from lead_cleaner.evaluation.quality_context import build_metadata as legacy_metadata
from lead_cleaner.evaluation.quality_context import git


EVALUATION_GROUPS = {
    "handbook": {"case_count": 18, "turn_count": 28, "retrieval_units": 39},
    "synthetic_special": {"case_count": 6, "turn_count": 8, "retrieval_units": 15},
}


def load_protocol(root: Path, protocol_id: str = "p0-02.v1") -> dict[str, Any]:
    spec = protocol_spec(protocol_id)
    protocol = json.loads((root / spec["policy_path"]).read_text("utf-8"))
    expected = {
        "rule_only": {"trials": 1, "case_count": 24, "turn_count": 36, "retrieval_units": 54},
        "mocked_model": {"trials": 1, "case_count": 24, "turn_count": 36, "retrieval_units": 0},
    }
    if (
        protocol.get("protocol_id") != protocol_id
        or protocol.get("schema_version") != spec["schema_version"]
        or protocol.get("rubric_version") != spec["rubric_version"]
        or protocol.get("modes") != expected
        or protocol.get("top_k") != 3
    ):
        raise ValueError("Unsupported answerability protocol or mode matrix")
    if protocol.get("assertion_ids") != [
        "execution",
        "facts_state",
        "answer_content",
        "grounding",
        "clarification",
    ] or protocol.get("paths") != ["raw_query", "runtime_rule_query", "runtime_fused_query"]:
        raise ValueError("Required observations cannot be removed from protocol")
    if protocol_id == "p0-02.v2" and protocol.get("evaluation_groups") != EVALUATION_GROUPS:
        raise ValueError("Evaluation groups must preserve the fixed handbook and synthetic cohorts")
    return protocol


def build_metadata(
    root: Path, dataset: dict[str, Any], mode: str, protocol: dict[str, Any]
) -> dict[str, Any]:
    spec = protocol_spec(protocol["protocol_id"])
    if dataset.get("protocol_id", "p0-02.v1") != protocol["protocol_id"]:
        raise ValueError("Dataset and scoring protocol do not match")
    if mode not in protocol["modes"]:
        raise ValueError("Unsupported offline mode")
    metadata = legacy_metadata(root, dataset["cases"], mode, protocol)
    package = root / "src/lead_cleaner/answerability_evaluation"
    files = [p.relative_to(root).as_posix() for p in package.glob("*.py")]
    files.extend(
        p.relative_to(root).as_posix() for p in (root / "scripts").glob("*answerability*.py")
    )
    # These old modules are used as primitives and remain byte-for-byte frozen.
    files.extend(
        [
            "src/lead_cleaner/evaluation/_quality_runtime.py",
            "src/lead_cleaner/evaluation/quality_context.py",
            "src/lead_cleaner/evaluation/quality_schema.py",
        ]
    )
    evaluator_files = {name: file_hash(root / name) for name in sorted(files)}
    dirty = git(
        root,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        "src",
        "scripts",
        "config",
        "data/answerability_eval",
        "pyproject.toml",
        "uv.lock",
        ".github",
    )
    reviewed = all(c["review_status"] == "reviewed" for c in dataset["cases"])
    metadata.update(
        schema_version=spec["schema_version"],
        protocol_id=spec["protocol_id"],
        protocol_hash=content_hash(protocol),
        rubric_hash=content_hash({"version": protocol["rubric_version"], "files": evaluator_files}),
        evaluator_hash=content_hash(evaluator_files),
        evaluator_files=evaluator_files,
        dataset_hash=dataset["dataset_hash"],
        knowledge_hash=dataset["knowledge_hash"],
        expected_keys=expected_keys(dataset, mode),
        expected_retrieval_keys=expected_retrieval_keys(dataset, mode),
        source_dirty=bool(dirty),
        provisional=bool(dirty) or not reviewed,
        business_labels_reviewed=reviewed,
        real_model_calls=0,
        live_status="not_run",
        mock_strategy=(
            "extract_provided_evidence_declarative.v2"
            if protocol["protocol_id"] == "p0-02.v2"
            else "extract_provided_evidence"
        )
        if mode == "mocked_model"
        else "not_applicable",
        predicted_answerability="not_observed",
    )
    if spec["protocol_id"] == "p0-02.v2":
        case_groups = {case["case_id"]: case["evaluation_group"] for case in dataset["cases"]}
        case_sources = {
            case["case_id"]: {
                field: case[field] for field in ("scenario_origin", "corpus_origin", "snapshot_id")
            }
            for case in dataset["cases"]
        }
        measured = {
            group: {
                "case_count": sum(c["evaluation_group"] == group for c in dataset["cases"]),
                "turn_count": sum(
                    len(c["turns"]) for c in dataset["cases"] if c["evaluation_group"] == group
                ),
                "retrieval_units": 3
                * sum(
                    c["evaluation_group"] == group and len(c["turns"]) == 1
                    for c in dataset["cases"]
                ),
            }
            for group in EVALUATION_GROUPS
        }
        if measured != EVALUATION_GROUPS or set(case_groups.values()) != set(EVALUATION_GROUPS):
            raise ValueError("Dataset evaluation groups differ from the fixed protocol")
        if content_hash(dataset["source_manifest"]) != dataset["source_manifest_hash"]:
            raise ValueError("Handbook source manifest hash does not match")
        binding = {
            "evaluation_groups": measured,
            "case_groups": case_groups,
            "case_sources": case_sources,
            "source_manifest_hash": dataset["source_manifest_hash"],
        }
        metadata.update(
            **binding,
            group_source_hash=content_hash(binding),
            source_manifest=dataset["source_manifest"],
            source_checkout_hashes=dataset.get("source_checkout_hashes", {}),
        )
    return metadata
