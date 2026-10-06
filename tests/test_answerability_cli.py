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
        assert report["metadata"]["protocol_id"] == "p0-02.v2"
        assert report["metrics"]["cross_group_accuracy"] == "not_computed"
        assert "replies" not in report["metrics"]
        for group, turns in (("handbook", 28), ("synthetic_special", 8)):
            aggregate = report["metrics"]["groups"][group]["replies"]["all"]
            assert aggregate["denominator"] == turns
            assert aggregate["adjudicated_count"] == 0
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


def test_historical_report_read_only_command_cannot_claim_approval(monkeypatch, capsys, tmp_path):
    original = {"metadata": {"protocol_id": "p0-02.v1"}, "manifest_hash": "a" * 64}
    monkeypatch.setattr(cli, "load_run", lambda path: original)
    assert cli.main(["verify-archive", "--run", str(tmp_path)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "sealed_bytes_verified"
    assert receipt["business_approval"] is False
    with pytest.raises(ReportError, match="read-only"):
        cli._active_runs([tmp_path])


def test_version_registry_rejects_arbitrary_protocol_or_path():
    from lead_cleaner.answerability_evaluation.registry import ACTIVE_PROTOCOL, protocol_spec

    assert ACTIVE_PROTOCOL == "p0-02.v2"
    assert protocol_spec(ACTIVE_PROTOCOL)["data_directory"] == "data/answerability_eval/v2"
    assert protocol_spec("p0-02.v1")["data_directory"] == "data/answerability_eval"
    for value in ("p0-01.v1", "../../weak", "p0-02.v3", ""):
        with pytest.raises(ValueError, match="Unsupported"):
            protocol_spec(value)


def test_archive_proposal_repoints_only_current_acceptance_and_keeps_prior_initial():
    old = {
        "acceptance_id": "old",
        "manifest_hash": "old-hash",
        "run": {"directory": "reports/quality/baselines/p0-02.v2/old/run"},
    }
    new = {
        "acceptance_id": "new",
        "manifest_hash": "new-hash",
        "run": {"directory": "data/runtime/staged"},
        "initial_baseline": old,
    }
    canonical = cli._canonical_records(
        new, {"new": ("reports/quality/baselines/p0-02.v2/new/run", "new-hash")}
    )
    assert canonical["run"]["directory"] == "reports/quality/baselines/p0-02.v2/new/run"
    assert canonical["initial_baseline"] == old
    assert new["run"]["directory"] == "data/runtime/staged"
    assert (
        cli._canonical_records([new], {"new": ("target", "new-hash")})[0]["run"]["directory"]
        == "target"
    )
    with pytest.raises(ReportError, match="staged archive"):
        cli._canonical_records(new, {"new": ("target", "wrong-hash")})


def test_accept_cli_stages_two_archives_and_canonical_configs_without_installing(
    real_runs, tmp_path, monkeypatch
):
    # Gate authorization is tested independently. This test exercises packaging
    # of already approved units without creating any real approval or baseline.
    import copy

    reports = [load_run(path) for path in real_runs]
    units = {
        run["metadata"]["mode"]: {
            "acceptance_id": "test-only-" + run["metadata"]["mode"],
            "manifest_hash": run["manifest_hash"],
            "run": copy.deepcopy(run),
        }
        for run in reports
    }
    proposal = {
        "protocol_id": "p0-02.v2",
        "accepted": units,
        "initial": units,
        "known_issues": [],
        "accepted_baselines": {},
        "latest_accepted_baselines": {
            mode: record["acceptance_id"] for mode, record in units.items()
        },
    }
    monkeypatch.setattr(cli, "verify_protected_files", lambda *args: {})
    monkeypatch.setattr(
        cli,
        "load_trust_context",
        lambda *args, **kw: {
            "protocol_id": "p0-02.v2",
            "trusted_ref": "test-only",
            "known_issues_hash": "x",
        },
    )
    monkeypatch.setattr(cli, "verify_github_artifacts", lambda *args, **kw: [])
    monkeypatch.setattr(cli, "trusted_json", lambda *args: {"issues": []})
    monkeypatch.setattr(cli, "_baselines", lambda *args: {})
    monkeypatch.setattr(cli, "accept_baselines", lambda *args, **kw: copy.deepcopy(proposal))
    index, approvals = tmp_path / "index.json", tmp_path / "approvals.json"
    index.write_text('{"reports": []}', encoding="utf-8")
    approvals.write_text("{}", encoding="utf-8")
    output = tmp_path / "proposal"
    args = argparse.Namespace(
        project_root=ROOT,
        out=output,
        run=real_runs,
        trusted_ref="test-only",
        review_set="empty",
        approvals=approvals,
        report_index=index,
    )
    result = cli._accept(args)
    assert result["status"] == "prepared_for_trusted_git_acceptance"
    installed = json.loads((output / "archive-installation.json").read_text("utf-8"))
    assert installed["status"] == "proposal_only_not_installed"
    assert len(installed["archives"]) == 2
    proposed = json.loads(
        (output / "proposed-config/quality_answerability_baseline_index.v2.json").read_text("utf-8")
    )
    for mode, record in proposed["accepted"].items():
        target = "reports/quality/baselines/p0-02.v2/test-only-" + mode + "/run"
        assert record["run"]["directory"] == target
        assert proposed["initial"][mode]["run"]["directory"] == target
        assert load_run(output / target)["manifest_hash"] == record["manifest_hash"]
    staged = json.loads((output / "proposal.json").read_text("utf-8"))
    staged_directory = Path(staged["accepted"]["rule_only"]["run"]["directory"])
    assert (ROOT / staged_directory).resolve() == (
        output / "reports/quality/baselines/p0-02.v2/test-only-rule_only/run"
    ).resolve()
    assert not (ROOT / "reports/quality/baselines/p0-02.v2/test-only-rule_only/run").exists()
    assert not (output / "proposed-config/quality_answerability_baseline_index.v1.json").exists()
    units["rule_only"]["acceptance_id"] = "nested/not-a-single-id"
    args.out = tmp_path / "invalid-proposal"
    with pytest.raises(ReportError, match="single safe"):
        cli._accept(args)
    assert not args.out.exists()


def test_nested_initial_archive_resolves_from_project_root_outside_cwd(
    real_runs, tmp_path, monkeypatch
):
    import shutil

    repository = tmp_path / "repository"
    relative = "reports/quality/baselines/p0-02.v2/"
    for identity in ("initial", "latest"):
        shutil.copytree(real_runs[0], repository / relative / identity / "run")
    original = load_run(real_runs[0])
    initial = {
        "acceptance_id": "initial",
        "manifest_hash": original["manifest_hash"],
        "run": {"directory": relative + "initial/run"},
    }
    latest = {
        "acceptance_id": "latest",
        "manifest_hash": original["manifest_hash"],
        "run": {"directory": relative + "latest/run"},
        "initial_baseline": initial,
    }
    monkeypatch.setattr(
        cli,
        "trusted_json",
        lambda *args: {
            "protocol_id": "p0-02.v2",
            "accepted": {"rule_only": latest},
        },
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    hydrated = cli._baselines(repository, "trusted-test-ref")["rule_only"]
    assert Path(hydrated["run"]["directory"]) == repository / relative / "latest/run"
    assert (
        Path(hydrated["initial_baseline"]["run"]["directory"])
        == repository / relative / "initial/run"
    )
    assert initial["run"]["directory"] == relative + "initial/run"
    initial["manifest_hash"] = "0" * 64
    with pytest.raises(ReportError, match="trusted index"):
        cli._baselines(repository, "trusted-test-ref")


@pytest.mark.parametrize("record", [None, {}, {"run": {}}, {"run": {"directory": 42}}])
def test_baseline_loader_rejects_missing_trusted_archive_shape(record, tmp_path):
    with pytest.raises(ReportError):
        cli._hydrate_baseline_record(tmp_path, record)
