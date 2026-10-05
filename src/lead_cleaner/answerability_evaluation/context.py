"""Fingerprint the actual local source and the independently versioned protocol."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lead_cleaner.answerability_evaluation.checks import expected_keys, expected_retrieval_keys
from lead_cleaner.answerability_evaluation.reports import content_hash, file_hash
from lead_cleaner.evaluation.quality_context import build_metadata as legacy_metadata
from lead_cleaner.evaluation.quality_context import git


def load_protocol(root: Path) -> dict[str, Any]:
    protocol = json.loads((root / "config/quality_answerability.v1.json").read_text("utf-8"))
    expected = {
        "rule_only": {"trials": 1, "case_count": 24, "turn_count": 36, "retrieval_units": 54},
        "mocked_model": {"trials": 1, "case_count": 24, "turn_count": 36, "retrieval_units": 0},
    }
    if (
        protocol.get("protocol_id") != "p0-02.v1"
        or protocol.get("schema_version") != "answerability-eval.v1"
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
    return protocol


def build_metadata(
    root: Path, dataset: dict[str, Any], mode: str, protocol: dict[str, Any]
) -> dict[str, Any]:
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
        schema_version="answerability-eval.v1",
        protocol_id="p0-02.v1",
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
        mock_strategy="extract_provided_evidence" if mode == "mocked_model" else "not_applicable",
        predicted_answerability="not_observed",
    )
    return metadata
