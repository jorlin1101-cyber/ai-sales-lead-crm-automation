"""V2 executes the real API using only frozen source text, not grading labels."""

from copy import deepcopy
from pathlib import Path
import json

import pytest

from lead_cleaner.answerability_evaluation import adapters, context, runner
from lead_cleaner.answerability_evaluation.checks import evaluate_assertions, expected_keys
from lead_cleaner.answerability_evaluation.dataset import load_dataset
from lead_cleaner.answerability_evaluation.metrics import aggregate_metrics, score_retrieval
from lead_cleaner.answerability_evaluation.retrieval import run_retrieval
from lead_cleaner.answerability_evaluation.reports import content_hash

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dataset_v2():
    return load_dataset(ROOT, "p0-02.v2")


@pytest.fixture(scope="module", params=adapters.MODES)
def executed_v2(request, dataset_v2, tmp_path_factory):
    mode = request.param
    observations = adapters.run_observations(ROOT, dataset_v2, mode, tmp_path_factory.mktemp(mode))
    rows = run_retrieval(dataset_v2) if mode == "rule_only" else []
    turns = {(c["case_id"], t["turn_id"]): t for c in dataset_v2["cases"] for t in c["turns"]}
    for row in rows:
        row["metrics"] = score_retrieval(
            turns[row["case_id"], row["turn_id"]],
            row["results"],
            execution_status=row["execution_status"],
        )
    assertions = evaluate_assertions(dataset_v2, observations)
    metrics = aggregate_metrics(dataset_v2, observations, assertions, rows, mode)
    return mode, observations, rows, assertions, metrics


def test_v2_actual_api_and_real_retrieval_keep_all_planned_units(dataset_v2, executed_v2):
    mode, observations, retrieval, assertions, metrics = executed_v2
    assert len(observations) == 36 and len(assertions) == 180
    assert len(retrieval) == (54 if mode == "rule_only" else 0)
    assert all(o["protocol_id"] == "p0-02.v2" and o["api_status"] == 200 for o in observations)
    assert all(o["execution_status"] == "completed" for o in observations)
    assert all(a["protocol_id"] == "p0-02.v2" for a in assertions)
    assert all(
        r["protocol_id"] == "p0-02.v2" and r["execution_status"] == "completed" for r in retrieval
    )
    assert all(key[0] == "p0-02.v2" for key in expected_keys(dataset_v2, mode))
    assert set(metrics) == {"groups", "cross_group_accuracy", "retrieval_applicability"}
    for group, turns, units in [("handbook", 28, 39), ("synthetic_special", 8, 15)]:
        values = metrics["groups"][group]
        assert values["counts"]["observed_turn_count"] == turns
        assert values["replies"]["all"]["denominator"] == turns
        assert values["counts"]["retrieval_units"] == (units if mode == "rule_only" else 0)
        assert values["counts"]["observed_retrieval_units"] == (units if mode == "rule_only" else 0)
    assert metrics["cross_group_accuracy"] == "not_computed"
    corrected = next(o for o in observations if o["case_id"] == "AB22" and o["turn_id"] == "T2")
    assert "9" in corrected["input_message"]
    # The legacy correction wording stays observable; no fixture-derived fact updates.
    assert any("8" in text for text in corrected["history"])


def test_v2_report_is_readable_and_separates_origins(dataset_v2, executed_v2):
    mode, obs, retrieval, assertions, metrics = executed_v2
    metadata = context.build_metadata(
        ROOT, dataset_v2, mode, context.load_protocol(ROOT, "p0-02.v2")
    )
    summary = runner.render_summary(metadata, assertions, obs, retrieval, metrics, dataset_v2)
    for text in [
        "p0-02.v2",
        "原手册业务组",
        "合成边界专项",
        "不计算混合产品准确率",
        "28 轮",
        "8 轮",
        "逐轮实际输出",
        "中文阅读译文",
        "标签审核：draft",
    ]:
        assert text in summary
    assert summary.count("客户提问（实际输入原文）") == 36
    assert summary.count("实际回复：") == 36
    assert dataset_v2["cases"][0]["turns"][0]["message"] in summary
    assert obs[0]["reply_text"] in summary.replace("> ", "")


def test_v2_source_and_group_labels_do_not_enter_system(dataset_v2, tmp_path):
    data = deepcopy(dataset_v2)
    data["cases"] = [c for c in data["cases"] if c["case_id"] == "AB19"]
    for case in data["cases"]:
        for field in ("evaluation_group", "scenario_origin", "corpus_origin"):
            case[field] = "HIDDEN_SOURCE_GOLD"
        for turn in case["turns"]:
            for field in ("message_zh", "answerability", "facets", "expected_facts", "judgments"):
                turn[field] = "HIDDEN_SOURCE_GOLD"
    for snapshot in data["snapshots"].values():
        snapshot["policy_conflicts"] = "HIDDEN_SOURCE_GOLD"
        snapshot["corpus_origin"] = "HIDDEN_SOURCE_GOLD"
    observations = adapters.run_observations(ROOT, data, "mocked_model", tmp_path)
    assert len(observations) == 3 and all(o["api_status"] == 200 for o in observations)
    assert "HIDDEN_SOURCE_GOLD" not in json.dumps(observations)


def test_v2_metadata_stably_binds_groups_and_sources(dataset_v2):
    protocol = context.load_protocol(ROOT, "p0-02.v2")
    first = context.build_metadata(ROOT, dataset_v2, "rule_only", protocol)
    binding = {
        k: first[k]
        for k in ("evaluation_groups", "case_groups", "case_sources", "source_manifest_hash")
    }
    assert first["group_source_hash"] == content_hash(binding)
    assert first["source_manifest_hash"] == content_hash(first["source_manifest"])
    assert first["case_sources"]["AB01"]["corpus_origin"] == "original_handbook"
    changed = deepcopy(dataset_v2)
    changed["source_checkout_hashes"] = {"platform_diagnostic": "different"}
    second = context.build_metadata(ROOT, changed, "rule_only", protocol)
    assert second["group_source_hash"] == first["group_source_hash"]
    assert second["source_manifest_hash"] == first["source_manifest_hash"]
    changed["cases"][0]["evaluation_group"] = "synthetic_special"
    with pytest.raises(ValueError, match="groups"):
        context.build_metadata(ROOT, changed, "rule_only", protocol)
    changed = deepcopy(dataset_v2)
    changed["source_manifest_hash"] = "0" * 64
    with pytest.raises(ValueError, match="manifest"):
        context.build_metadata(ROOT, changed, "rule_only", protocol)
    with pytest.raises(ValueError, match="do not match"):
        context.build_metadata(ROOT, dataset_v2, "rule_only", context.load_protocol(ROOT))


def test_v2_group_contract_cannot_be_removed(tmp_path):
    protocol = context.load_protocol(ROOT, "p0-02.v2")
    (tmp_path / "config").mkdir()
    protocol["evaluation_groups"]["handbook"]["turn_count"] = 27
    (tmp_path / "config/quality_answerability.v2.json").write_text(
        json.dumps(protocol), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Evaluation groups"):
        context.load_protocol(tmp_path, "p0-02.v2")


def test_v2_mock_strategy_is_generic_declarative_and_v1_stays_unchanged():
    payload = {
        "evidence": [
            {"evidence_id": "h", "quote": "# Handbook"},
            {"evidence_id": "q", "quote": "Which deposit is needed?"},
            {"evidence_id": "qz", "quote": "需要定金吗？"},
            {"evidence_id": "a", "quote": "A: A deposit is required."},
            {"evidence_id": "empty", "quote": "  "},
            {"evidence_id": "b", "quote": "The amount depends on the quotation."},
        ]
    }
    before = deepcopy(payload)
    assert [p["evidence_id"] for p in adapters.ControlledClient.respond(payload)["paragraphs"]] == [
        "h",
        "q",
        "qz",
    ]
    assert [
        p["evidence_id"]
        for p in adapters.DeclarativeControlledClient.respond(payload)["paragraphs"]
    ] == ["a", "b"]
    assert payload == before
    assert adapters.DeclarativeControlledClient.respond({"current_message": "8 people"}) == {
        "updates": []
    }
    assert adapters.DeclarativeControlledClient.respond({"evidence": payload["evidence"][:3]}) == {
        "paragraphs": []
    }


def test_v2_empty_declarative_output_keeps_real_guard_rejection(dataset_v2, tmp_path, monkeypatch):
    original = adapters.DeclarativeControlledClient.respond

    def questions_only(payload):
        if "evidence" in payload:
            return original({"evidence": [{"evidence_id": "q", "quote": "Which date?"}]})
        return original(payload)

    monkeypatch.setattr(
        adapters.DeclarativeControlledClient, "respond", staticmethod(questions_only)
    )
    data = deepcopy(dataset_v2)
    data["cases"] = data["cases"][:1]
    row = adapters.run_observations(ROOT, data, "mocked_model", tmp_path)[0]
    assert row["api_status"] == 200
    assert row["execution_status"] == "error"
    assert row["error_type"] == "invalid_structured_output"
    assert row["stages"][1]["fallback_used"] is True
    assert row["provided_context"] == row["provided_context_rule"]
    assert row["model_calls"][1]["response"] == {"paragraphs": []}
    assert row["reply_text"]
