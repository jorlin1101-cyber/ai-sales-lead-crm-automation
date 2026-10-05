"""Composition tests run actual production paths, plus fail-closed CLI boundaries."""

import argparse
import json
from pathlib import Path

import pytest

from lead_cleaner.answerability_evaluation import cli, context, runner
from lead_cleaner.answerability_evaluation.reports import ReportError, load_run

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def real_runs(tmp_path_factory):
    directory = tmp_path_factory.mktemp("answerability-real-cli")
    paths = []
    for mode in ("rule_only", "mocked_model"):
        path = directory / mode
        assert (
            cli.main(["--project-root", str(ROOT), "run", "--mode", mode, "--out", str(path)]) == 0
        )
        paths.append(path)
    return paths


def test_real_cli_records_all_observations_and_metrics(real_runs, tmp_path):
    for path in real_runs:
        report = load_run(path)
        assert len(report["observations"]) == 36
        assert len(report["assertions"]) == 180
        assert len(report["retrieval"]) == (54 if path.name == "rule_only" else 0)
        assert report["metadata"]["real_model_calls"] == 0
        assert report["metadata"]["provisional"]
        assert report["metrics"]["replies"]["all"]["denominator"] == 36
        assert report["metrics"]["replies"]["all"]["adjudicated_count"] == 0
        args = [
            "check",
            "--gate",
            "inventory",
            "--run",
            str(path),
            "--candidate-sha",
            report["metadata"]["tested_commit"],
            "--out",
            str(tmp_path / path.name),
        ]
        assert cli.main(args) == 0
        decision = json.loads((tmp_path / path.name / "decision.json").read_text("utf-8"))
        assert decision["provisional"]
        assert "effective_metrics" in decision


def test_review_template_is_unapproved_and_cannot_be_applied_locally(real_runs, tmp_path):
    out = tmp_path / "reviews.json"
    assert (
        cli.main(
            [
                "review-template",
                "--run",
                str(real_runs[0]),
                "--run",
                str(real_runs[1]),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    review = json.loads(out.read_text("utf-8"))
    assert review["review_set_id"] == "draft-not-approved"
    assert len(review["reviews"]) == 36 * 3 * 2 * 2
    assert all(
        not r["reviewer"] and r["semantic"]["claims_complete"] is False for r in review["reviews"]
    )
    assert (
        cli.main(
            [
                "check",
                "--gate",
                "behavior",
                "--run",
                str(real_runs[0]),
                "--candidate-sha",
                "a" * 40,
                "--review-set",
                str(out),
                "--out",
                str(tmp_path / "bad"),
            ]
        )
        == 3
    )


def test_cli_rejects_incomplete_trust_and_existing_output(real_runs, tmp_path):
    assert cli.main(["run", "--mode", "rule_only", "--out", str(real_runs[0])]) == 2
    assert (
        cli.main(
            [
                "check",
                "--gate",
                "regression",
                "--run",
                str(real_runs[0]),
                "--candidate-sha",
                "a" * 40,
                "--out",
                str(tmp_path / "bad"),
            ]
        )
        == 3
    )
    assert (
        cli.main(
            [
                "check",
                "--gate",
                "inventory",
                "--run",
                str(tmp_path / "absent"),
                "--candidate-sha",
                "a" * 40,
                "--out",
                str(tmp_path / "none"),
            ]
        )
        == 3
    )
    assert (
        cli.main(
            [
                "accept",
                "--run",
                str(real_runs[0]),
                "--trusted-ref",
                "a" * 40,
                "--review-set",
                "empty",
                "--approvals",
                str(tmp_path / "approval"),
                "--report-index",
                str(tmp_path / "index"),
                "--out",
                str(tmp_path / "accept"),
            ]
        )
        == 3
    )


def test_context_rejects_mode_matrix_or_removed_assertion(tmp_path):
    (tmp_path / "config").mkdir()
    original = context.load_protocol(ROOT)
    for field, value in [("top_k", 4), ("assertion_ids", []), ("paths", [])]:
        (tmp_path / "config/quality_answerability.v1.json").write_text(
            json.dumps(original | {field: value}), encoding="utf-8"
        )
        with pytest.raises(ValueError):
            context.load_protocol(tmp_path)
    with pytest.raises(ValueError):
        context.build_metadata(ROOT, {}, "live", original)


def test_runner_rejects_reused_workspace(tmp_path):
    output = tmp_path / "report"
    output.with_name("report.work").mkdir()
    with pytest.raises(ValueError, match="workspace"):
        runner.run_suite(ROOT, "rule_only", output)


def test_cli_returns_execution_failures_without_claiming_business_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cli,
        "run_suite",
        lambda *a: {
            "observations": [{"execution_status": "error"}],
            "retrieval": [],
            "manifest_hash": "h",
            "metadata": {"provisional": True},
            "directory": str(tmp_path),
        },
    )
    assert cli.main(["run", "--mode", "rule_only", "--out", str(tmp_path)]) == 2


def test_accept_does_not_overwrite_existing_proposal(tmp_path):
    args = argparse.Namespace(project_root=ROOT, out=tmp_path)
    with pytest.raises(ReportError, match="already exists"):
        cli._accept(args)


def test_behavior_cannot_omit_the_other_required_mode(real_runs, tmp_path):
    run = load_run(real_runs[0])
    output = tmp_path / "behavior"
    assert (
        cli.main(
            [
                "check",
                "--gate",
                "behavior",
                "--run",
                str(real_runs[0]),
                "--candidate-sha",
                run["metadata"]["tested_commit"],
                "--out",
                str(output),
            ]
        )
        != 0
    )
    decision = json.loads((output / "decision.json").read_text("utf-8"))
    assert any(item["message"] == "Required mode report is missing" for item in decision["reasons"])
