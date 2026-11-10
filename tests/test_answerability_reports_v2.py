"""V2 protocol isolation and source/group integrity; all authority is synthetic."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from lead_cleaner.answerability_evaluation import gates, provenance, reports, review_reuse, trust
from lead_cleaner.answerability_evaluation.registry import protocol_spec
from lead_cleaner.answerability_evaluation.metrics import aggregate_metrics, ratio
from tests.test_answerability_reports import (
    REFERENCE,
    artifact,
    authorize,
    check,
    provider_fixture,
    raw,
    reviews_for,
    trusted,
)


PROTOCOL = "p0-02.v2"
PATHS = ("raw_query", "runtime_rule_query", "runtime_fused_query")


def raw_v2(mode="rule_only"):
    template = raw(mode)
    metadata = copy.deepcopy(template["metadata"])
    metadata.update(schema_version="answerability-eval.v2", protocol_id=PROTOCOL)
    observations, assertions, retrieval = [], [], []
    mapping, sources = {}, {}
    for number in range(1, 25):
        case_id = f"AB{number:02d}"
        group = "synthetic_special" if case_id in reports.V2_SPECIAL_CASES else "handbook"
        mapping[case_id] = group
        sources[case_id] = {
            "scenario_origin": "synthetic_question",
            "corpus_origin": "original_handbook" if group == "handbook" else "synthetic_fixture",
            "snapshot_id": "unit-" + group,
        }
        for turn_id in ["T1", "T2", "T3"] if number >= 19 else ["T1"]:
            observation = dict(
                template["observations"][0], protocol_id=PROTOCOL, case_id=case_id, turn_id=turn_id
            )
            observations.append(observation)
            for assertion_id in (
                "execution",
                "facts_state",
                "answer_content",
                "grounding",
                "clarification",
            ):
                assertions.append(
                    dict(
                        template["assertions"][0],
                        protocol_id=PROTOCOL,
                        case_id=case_id,
                        turn_id=turn_id,
                        assertion_id=assertion_id,
                        observation_hash=reports.content_hash(observation),
                    )
                )
        if number < 19 and mode == "rule_only":
            for path in PATHS:
                retrieval.append(
                    dict(
                        copy.deepcopy(template["retrieval"][0]),
                        protocol_id=PROTOCOL,
                        case_id=case_id,
                        turn_id="T1",
                        path=path,
                    )
                )
    metadata.update(
        expected_keys=[list(reports.key(row)) for row in assertions],
        expected_retrieval_keys=[[row["case_id"], row["path"]] for row in retrieval],
        evaluation_groups=copy.deepcopy(reports.V2_GROUPS),
        case_groups=mapping,
        case_sources=sources,
        source_manifest={
            "schema_version": "answerability-source-manifest.v2",
            "unit_fixture": True,
        },
    )
    metadata["source_manifest_hash"] = reports.content_hash(metadata["source_manifest"])
    metadata["group_source_hash"] = reports.content_hash(reports.group_binding(metadata))
    for row in retrieval:
        row["metrics"] = {
            name: ratio(0 if name == "unjudged_rate" else 1, 1) for name in reports.METRICS
        }
    data = {
        "metadata": metadata,
        "observations": observations,
        "assertions": assertions,
        "retrieval": retrieval,
    }
    data["metrics"] = aggregate_metrics(v2_dataset(data), observations, assertions, retrieval, mode)
    return data


def v2_dataset(data):
    meta = data["metadata"]
    dataset = {
        field: copy.deepcopy(meta[field])
        for field in (
            "protocol_id",
            "dataset_hash",
            "knowledge_hash",
            "source_manifest_hash",
            "source_manifest",
        )
    }
    dataset["cases"] = [
        {
            "case_id": case_id,
            "language": "zh"
            if int(case_id[2:]) <= 10
            else "en"
            if int(case_id[2:]) <= 20
            else "mixed",
            "evaluation_group": group,
            **meta["case_sources"][case_id],
            "turns": [
                {
                    "turn_id": turn_id,
                    "answerability": "answerable",
                    "judgments": {},
                    "facets": [
                        {
                            "facet_id": "unit",
                            "required": True,
                            "answerable": True,
                            "reasons": [],
                            "support_groups": [],
                        }
                    ],
                }
                for turn_id in (["T1", "T2", "T3"] if int(case_id[2:]) >= 19 else ["T1"])
            ],
        }
        for case_id, group in meta["case_groups"].items()
    ]
    return dataset


def rebind(data):
    meta = data["metadata"]
    meta["source_manifest_hash"] = reports.content_hash(meta["source_manifest"])
    meta["group_source_hash"] = reports.content_hash(reports.group_binding(meta))
    meta["expected_keys"] = [list(reports.key(row)) for row in data["assertions"]]
    meta["expected_retrieval_keys"] = [[r["case_id"], r["path"]] for r in data["retrieval"]]
    observations = {
        reports.key(row, reports.OBSERVATION_FIELDS): row for row in data["observations"]
    }
    for row in data["assertions"]:
        row["observation_hash"] = reports.content_hash(
            observations[reports.key(row, reports.OBSERVATION_FIELDS)]
        )


def v2_trust(run):
    value = trusted(run)
    value["protocol_id"] = PROTOCOL
    value["verified_artifacts"] = [
        artifact(run) | {f: run["metadata"][f] for f in ("protocol_id", *reports.V2_BINDINGS)}
    ]
    return value


@pytest.mark.parametrize("mode", ["rule_only", "mocked_model"])
def test_v2_seal_preserves_version_and_fixed_cohorts(tmp_path, mode):
    data = raw_v2(mode)
    run = reports.seal_run(tmp_path / mode, data)
    assert run["manifest"]["storage_version"] == "answerability-run.v2"
    assert len(run["observations"]) == 36 and len(run["assertions"]) == 180
    assert len(run["retrieval"]) == (54 if mode == "rule_only" else 0)
    assert check("inventory", run)["exit_code"] == 0
    assert check("behavior", run, trust_context=v2_trust(run))["exit_code"] == 0
    legacy = reports.seal_run(tmp_path / "historical-v1", raw(mode))
    before = {p.name: p.read_bytes() for p in Path(legacy["directory"]).iterdir()}
    assert (
        reports.load_run(legacy["directory"])["manifest"]["storage_version"]
        == "answerability-run.v1"
    )
    assert {p.name: p.read_bytes() for p in Path(legacy["directory"]).iterdir()} == before


@pytest.mark.parametrize(
    "change",
    [
        "group_count",
        "group_map",
        "missing_source",
        "source_extra",
        "source_category",
        "source_manifest",
        "manifest_version",
        "source_hash",
        "group_hash",
        "missing_case",
        "missing_turn",
        "missing_assertion",
        "optional_assertion",
        "group_leak",
        "missing_retrieval",
        "path",
        "retrieval_protocol",
        "retrieval_turn",
        "combined_accuracy",
        "combined_replies",
        "missing_group",
        "counts",
        "planned",
        "denominator",
        "bad_metric",
        "bad_unobserved",
        "source_empty",
        "replies_type",
    ],
)
def test_v2_cannot_shrink_cohorts_or_relabel_sources(tmp_path, change):
    data = raw_v2()
    meta = data["metadata"]
    if change == "group_count":
        meta["evaluation_groups"]["handbook"]["turn_count"] = 27
    elif change == "group_map":
        meta["case_groups"]["AB01"] = "synthetic_special"
    elif change == "missing_source":
        del meta["case_sources"]["AB01"]
    elif change == "source_extra":
        meta["case_sources"]["AB01"]["arbitrary"] = "weaker"
    elif change == "source_category":
        meta["case_sources"]["AB01"]["corpus_origin"] = "synthetic_fixture"
    elif change == "source_manifest":
        meta["source_manifest"] = []
    elif change == "manifest_version":
        meta["source_manifest"]["schema_version"] = "answerability-source-manifest.v1"
    elif change == "source_hash":
        meta["source_manifest_hash"] = "forged"
    elif change == "group_hash":
        meta["group_source_hash"] = "forged"
    elif change in {"missing_case", "missing_turn"}:

        def rejected(row):
            return (
                row["case_id"] == ("AB01" if change == "missing_case" else "AB19")
                and row["turn_id"] == "T1"
            )

        data["observations"] = [r for r in data["observations"] if not rejected(r)]
        data["assertions"] = [r for r in data["assertions"] if not rejected(r)]
    elif change == "missing_assertion":
        data["assertions"].pop(0)
    elif change == "optional_assertion":
        data["assertions"][0]["mandatory"] = False
    elif change == "group_leak":
        data["observations"][0]["evaluation_group"] = "handbook"
    elif change == "missing_retrieval":
        data["retrieval"].pop(0)
    elif change == "path":
        for row in data["retrieval"]:
            if row["path"] == "raw_query":
                row["path"] = "weaker_path"
    elif change == "retrieval_protocol":
        data["retrieval"][0]["protocol_id"] = "p0-02.v1"
    elif change == "retrieval_turn":
        data["retrieval"][0]["turn_id"] = "T2"
    elif change == "combined_accuracy":
        data["metrics"]["cross_group_accuracy"] = 1.0
    elif change == "combined_replies":
        data["metrics"]["replies"] = {"all": 1}
    elif change == "missing_group":
        del data["metrics"]["groups"]["synthetic_special"]
    elif change == "counts":
        data["metrics"]["groups"]["handbook"]["counts"]["turn_count"] = 27
    elif change == "planned":
        data["metrics"]["groups"]["handbook"]["replies"]["all"]["planned_count"] = 27
    elif change == "denominator":
        data["metrics"]["groups"]["handbook"]["replies"]["all"]["denominator"] = 27
    elif change == "bad_metric":
        data["metrics"]["groups"]["handbook"]["replies"]["all"]["value"] = 2
    elif change == "bad_unobserved":
        data["metrics"]["groups"]["handbook"]["replies"]["predicted_answerability"]["value"] = 1
    elif change == "source_empty":
        meta["case_sources"]["AB01"]["snapshot_id"] = ""
    elif change == "replies_type":
        data["metrics"]["groups"]["handbook"]["replies"] = []
    if change not in {"source_hash", "group_hash"}:
        rebind(data)
    with pytest.raises(reports.ReportError):
        reports.seal_run(tmp_path / "bad", data)


def test_storage_version_cannot_mislabel_verified_metadata(tmp_path):
    run = reports.seal_run(tmp_path / "run", raw_v2())
    directory = Path(run["directory"])
    manifest = reports.read_json(directory / "manifest.json")
    manifest["storage_version"] = "answerability-run.v1"
    (directory / "manifest.json").write_bytes(reports.canonical_json(manifest))
    (directory / "COMPLETED").write_text(
        reports.file_hash(directory / "manifest.json"), encoding="ascii"
    )
    with pytest.raises(reports.ReportError, match="Storage"):
        reports.load_run(directory)


def test_trust_registry_reads_only_selected_fixed_paths(monkeypatch, tmp_path):
    seen = []
    spec = protocol_spec(PROTOCOL)
    values = {
        spec["trust_path"]: {"protocol_id": PROTOCOL},
        spec["issues_path"]: {"protocol_id": PROTOCOL, "issues": []},
    }

    def loader(root, ref, path):
        seen.append(path)
        return values[path]

    monkeypatch.setattr(trust, "trusted_json", loader)
    assert trust.load_trust_context(tmp_path, REFERENCE, PROTOCOL)["protocol_id"] == PROTOCOL
    assert seen == [spec["trust_path"], spec["issues_path"]]
    values[spec["issues_path"]]["protocol_id"] = "p0-02.v1"
    with pytest.raises(reports.ReportError, match="issues"):
        trust.load_trust_context(tmp_path, REFERENCE, PROTOCOL)
    with pytest.raises(ValueError):
        trust.load_trust_context(tmp_path, REFERENCE, "../../weak")


@pytest.mark.parametrize("old_authority", [True, False])
def test_formal_v2_requires_explicit_same_protocol_trust(tmp_path, old_authority):
    run = reports.seal_run(tmp_path / "v2", raw_v2())
    context = trusted(run) if old_authority else {}
    assert check("behavior", run, trust_context=context)["exit_code"] == 3
    assert check("inventory", run, trust_context=trusted(run))["exit_code"] == 3
    with pytest.raises(reports.ReportError, match="protocol"):
        gates.accept_baseline(
            run, previous=None, known_issues=[], approval={}, trust_context=context
        )


def test_v2_approval_requires_both_bindings_and_archive_namespace(tmp_path):
    run = reports.seal_run(tmp_path / "v2", raw_v2())
    context = v2_trust(run)
    approval = authorize(run, context)
    with pytest.raises(reports.ReportError, match="binding"):
        gates.accept_baseline(
            run, previous=None, known_issues=[], approval=approval, trust_context=context
        )
    context["approval_bindings"][approval["approval_ref"]].update(
        {f: run["metadata"][f] for f in reports.V2_BINDINGS}
    )
    accepted = gates.accept_baseline(
        run, previous=None, known_issues=[], approval=approval, trust_context=context
    )
    assert accepted["protocol_id"] == PROTOCOL
    assert accepted["baseline_directory"] == "reports/quality/baselines/p0-02.v2"
    assert (
        accepted["approval_binding"]["source_manifest_hash"]
        == run["metadata"]["source_manifest_hash"]
    )
    context["verified_artifacts"] = [artifact(run)]
    with pytest.raises(reports.ReportError, match="provider-verified"):
        gates.accept_baseline(
            run, previous=None, known_issues=[], approval=approval, trust_context=context
        )


def test_v2_provider_derives_binding_after_exact_zip_validation(tmp_path, monkeypatch):
    run = reports.seal_run(tmp_path / "v2", raw_v2())
    entry, payload, policy = provider_fixture(run, monkeypatch)
    policy["protocol_id"] = PROTOCOL
    receipt = provenance.verify_github_artifacts(
        tmp_path, REFERENCE, [entry], getter=payload.__getitem__, protocol_id=PROTOCOL
    )[0]
    assert receipt["source_manifest_hash"] == run["metadata"]["source_manifest_hash"]
    assert (
        provenance.require_verified_artifact(
            run, {"protocol_id": PROTOCOL, "verified_artifacts": [receipt]}
        )
        == receipt
    )
    entry["provenance"]["group_source_hash"] = "forged"
    with pytest.raises(reports.ReportError, match="binding"):
        provenance.verify_github_artifacts(
            tmp_path, REFERENCE, [entry], getter=payload.__getitem__, protocol_id=PROTOCOL
        )
    old = reports.seal_run(tmp_path / "v1", raw())
    entry["directory"] = old["directory"]
    with pytest.raises(reports.ReportError, match="protocol"):
        provenance.verify_github_artifacts(
            tmp_path, REFERENCE, [entry], getter=payload.__getitem__, protocol_id=PROTOCOL
        )


def test_v2_rejects_old_reviews_even_when_manifest_is_not_current(tmp_path):
    old = reports.seal_run(tmp_path / "old", raw(status="needs_review"))
    new = reports.seal_run(tmp_path / "new", raw_v2())
    reviews = reviews_for(old)
    context = v2_trust(new)
    context["accepted_review_set_hashes"] = [reports.content_hash(reviews)]
    with pytest.raises(reports.ReportError, match="cross protocol"):
        trust.effective_assertions(new, reviews, context)
    for r in reviews["reviews"]:
        r["key"][0] = PROTOCOL
    context["accepted_review_set_hashes"] = [reports.content_hash(reviews)]
    with pytest.raises(reports.ReportError, match="source/group"):
        trust.effective_assertions(new, reviews, context)


def test_v2_dataset_binding_cannot_move_case_between_sources(tmp_path):
    data = raw_v2()
    run = reports.seal_run(tmp_path / "run", data)
    metadata = data["metadata"]
    dataset = {
        field: metadata[field]
        for field in ("protocol_id", "dataset_hash", "knowledge_hash", "source_manifest_hash")
    }
    dataset["source_manifest"] = copy.deepcopy(metadata["source_manifest"])
    dataset["cases"] = [
        {"case_id": case_id, "evaluation_group": group, **metadata["case_sources"][case_id]}
        for case_id, group in metadata["case_groups"].items()
    ]
    trust.validate_review_dataset(run, dataset)
    dataset["cases"][0]["evaluation_group"] = "synthetic_special"
    with pytest.raises(reports.ReportError, match="groups"):
        trust.validate_review_dataset(run, dataset)
    dataset["protocol_id"] = "p0-02.v1"
    with pytest.raises(reports.ReportError, match="protocol"):
        trust.validate_review_dataset(run, dataset)


def test_cross_version_baseline_and_derived_reuse_are_rejected(tmp_path):
    old = reports.seal_run(tmp_path / "old", raw())
    new = reports.seal_run(tmp_path / "new", raw_v2())
    with pytest.raises(reports.ReportError, match="comparison"):
        gates._comparable(old, new)
    with pytest.raises(reports.ReportError, match="protocol"):
        review_reuse.reuse_reviewed_assertions(old, {}, new, new["assertions"], v2_trust(new), {})
    with pytest.raises(reports.ReportError, match="fingerprints"):
        gates.accept_baselines(
            [old, reports.seal_run(tmp_path / "mock", raw_v2("mocked_model"))],
            previous={},
            known_issues=[],
            approvals={},
            trust_context=v2_trust(new),
        )


def v2_semantic_case(tmp_path):
    """Exercise v2 review bindings with one real observed output inside full storage cohorts."""
    from lead_cleaner.answerability_evaluation import checks
    from tests.test_answerability_review_reuse import semantic_case

    original = semantic_case(tmp_path / "v1-api-shape")
    dataset = copy.deepcopy(original["dataset"])
    dataset["protocol_id"] = PROTOCOL
    template = raw_v2("mocked_model")
    meta = template["metadata"]
    dataset.update(
        {field: meta[field] for field in ("dataset_hash", "knowledge_hash", "source_manifest_hash")}
    )
    dataset["source_manifest"] = copy.deepcopy(meta["source_manifest"])
    template_turn = dataset["cases"][0]["turns"][0]
    dataset["cases"] = []
    for case_id, group in meta["case_groups"].items():
        turns = [
            {**copy.deepcopy(template_turn), "turn_id": turn_id}
            for turn_id in (["T1", "T2", "T3"] if int(case_id[2:]) >= 19 else ["T1"])
        ]
        dataset["cases"].append(
            {
                "case_id": case_id,
                "language": "zh"
                if int(case_id[2:]) <= 10
                else "en"
                if int(case_id[2:]) <= 20
                else "mixed",
                "evaluation_group": group,
                "turns": turns,
                **meta["case_sources"][case_id],
            }
        )
    dataset["snapshots"] = {
        "unit-handbook": original["dataset"]["snapshots"]["unit"],
        "unit-synthetic_special": original["dataset"]["snapshots"]["unit"],
    }
    runs = []
    for name in ("baseline", "candidate"):
        data = copy.deepcopy(template)
        observation = copy.deepcopy(original[name]["observations"][0])
        observation["protocol_id"] = PROTOCOL
        data["observations"][0] = observation
        data["assertions"][:5] = checks.score_observation(
            template_turn, dataset["snapshots"]["unit-handbook"], observation
        )
        data["metadata"]["tested_commit"] = original[name]["metadata"]["tested_commit"]
        rebind(data)
        data["metrics"] = aggregate_metrics(
            dataset, data["observations"], data["assertions"], data["retrieval"], "mocked_model"
        )
        runs.append(reports.seal_run(tmp_path / ("v2-" + name), data))
    baseline, candidate = runs
    reviews = copy.deepcopy(original["reviews"])
    for review in reviews["reviews"]:
        review["key"][0] = PROTOCOL
        review["run_manifest_hash"] = baseline["manifest_hash"]
        review["output_hash"] = reports.content_hash(baseline["observations"][0])
        review["rubric_hash"] = meta["rubric_hash"]
        review.update({field: meta[field] for field in reports.V2_BINDINGS})
        review["semantic"]["observation_hash"] = review["output_hash"]
        review["semantic"]["rubric_version"] = "answerability-rubric.v2"
    context = v2_trust(candidate)
    context.update(
        accepted_baselines={"v2-initial": baseline["manifest_hash"]},
        latest_accepted_baselines={"mocked_model": "v2-initial"},
        accepted_review_set_hashes=[reports.content_hash(reviews)],
    )
    record = {
        "acceptance_id": "v2-initial",
        "run": baseline,
        "manifest_hash": baseline["manifest_hash"],
        "review_set": reviews,
        "review_set_hash": reports.content_hash(reviews),
        "known_issues": [],
        "known_issues_hash": reports.content_hash([]),
    }
    return {
        "baseline": baseline,
        "candidate": candidate,
        "dataset": dataset,
        "trust": context,
        "record": record,
        "reviews": reviews,
        "issues": [],
    }


def test_v2_review_and_derived_chain_bind_source_manifest_and_groups(tmp_path):
    from tests.test_answerability_review_reuse import reuse

    case = v2_semantic_case(tmp_path)
    rows, derived = reuse(case)
    assert len(derived) == 3
    assert all(r["behavior_status"] == "pass" for r in rows)
    assert all(
        r["protocol_id"] == PROTOCOL
        and r["source_manifest_hash"] == case["candidate"]["metadata"]["source_manifest_hash"]
        and r["group_source_hash"] == case["candidate"]["metadata"]["group_source_hash"]
        for r in derived
    )
    decision = check(
        "regression",
        case["candidate"],
        candidate_sha="b" * 40,
        baselines={"mocked_model": case["record"]},
        known_issues=[],
        trust_context=case["trust"],
        dataset=case["dataset"],
    )
    assert decision["exit_code"] == 0
    assert len(decision["derived_adjudications"]["mocked_model"]) == 3
    assert (
        check(
            "behavior",
            case["candidate"],
            candidate_sha="b" * 40,
            trust_context=case["trust"],
            dataset=case["dataset"],
        )["exit_code"]
        == 1
    )
    for review in case["reviews"]["reviews"]:
        review["source_manifest_hash"] = "self-signed-source"
    case["trust"]["accepted_review_set_hashes"] = [reports.content_hash(case["reviews"])]
    case["record"]["review_set_hash"] = reports.content_hash(case["reviews"])
    with pytest.raises(reports.ReportError, match="source/group"):
        reuse(case)


@pytest.mark.parametrize("changed", ["source", "group"])
def test_v2_semantic_reuse_rejects_resealed_changed_source_inputs(tmp_path, changed):
    from tests.test_answerability_review_reuse import reuse, reseal

    case = v2_semantic_case(tmp_path)

    def transform(data):
        if changed == "source":
            data["metadata"]["source_manifest"]["unit_fixture"] = "changed"
        else:
            data["metadata"]["case_sources"]["AB01"]["snapshot_id"] = "replacement"
        rebind(data)

    reseal(case, tmp_path / "resealed", transform)
    with pytest.raises(reports.ReportError, match="frozen"):
        reuse(case)
    assert (
        check(
            "regression",
            case["candidate"],
            candidate_sha="b" * 40,
            baselines={"mocked_model": case["record"]},
            known_issues=[],
            trust_context=case["trust"],
            dataset=case["dataset"],
        )["exit_code"]
        == 3
    )


def test_v2_known_issues_are_separate_and_atomic_initial_acceptance_is_v2(tmp_path):
    runs = [
        reports.seal_run(tmp_path / mode, raw_v2(mode)) for mode in ("rule_only", "mocked_model")
    ]
    context = v2_trust(runs[0])
    context["verified_artifacts"].extend(v2_trust(runs[1])["verified_artifacts"])
    approvals = {}
    for run in runs:
        mode = run["metadata"]["mode"]
        approvals[mode] = authorize(run, context, identifier=mode + "-v2")
        context["approval_bindings"][mode + "-v2"].update(
            {f: run["metadata"][f] for f in reports.V2_BINDINGS}
        )
    proposal = gates.accept_baselines(
        runs, previous={}, known_issues=[], approvals=approvals, trust_context=context
    )
    assert proposal["protocol_id"] == PROTOCOL
    assert proposal["baseline_directory"] == "reports/quality/baselines/p0-02.v2"
    assert set(proposal["initial"]) == {"rule_only", "mocked_model"}
    row = runs[0]["assertions"][0]
    issue = {
        "issue_id": "unit-old",
        "status": "open",
        **{f: row.get(f) for f in gates.ISSUE_FIELDS},
    }
    issue.update(protocol_id="p0-02.v1", failure_type="unit-failure")
    result = check("inventory", runs[0], known_issues=[issue], trust_context=context)
    assert result["exit_code"] == 3
    issue["protocol_id"] = PROTOCOL
    gates._issues([issue], PROTOCOL)


@pytest.mark.parametrize(
    "change",
    [
        "retrieval_empty",
        "retrieval_path",
        "retrieval_metric",
        "retrieval_denominator",
        "raw_retrieval_coverage",
        "state_missing",
        "state_extra",
        "state_shrink",
        "state_planned",
        "language_missing",
        "language_shrink",
        "turns_missing",
        "turns_type",
        "retrieval_applicability",
    ],
)
def test_v2_group_summaries_cannot_omit_paths_or_cohorts(tmp_path, change):
    data = raw_v2()
    group = data["metrics"]["groups"]["handbook"]
    if change == "retrieval_empty":
        group["retrieval"] = {}
    elif change == "retrieval_path":
        del group["retrieval"]["raw_query"]
    elif change == "retrieval_metric":
        del group["retrieval"]["raw_query"]["ndcg"]
    elif change == "retrieval_denominator":
        group["retrieval"]["raw_query"]["supported_facet_hit"]["denominator"] -= 1
    elif change == "raw_retrieval_coverage":
        del data["retrieval"][0]["metrics"]["ndcg"]["needs_review_count"]
    elif change == "state_missing":
        del group["replies"]["state:unanswerable"]
    elif change == "state_extra":
        group["replies"]["state:ignored"] = ratio(0, 0)
    elif change == "state_shrink":
        group["replies"]["state:answerable"] = ratio(27, 27)
    elif change == "state_planned":
        group["replies"]["state:answerable"]["planned_count"] -= 1
    elif change == "language_missing":
        del group["replies"]["language:mixed"]
    elif change == "language_shrink":
        group["replies"]["language:mixed"] = ratio(0, 0)
    elif change == "turns_missing":
        del group["replies"]["turns:multi"]
    elif change == "turns_type":
        group["replies"]["turns:multi"]["denominator"] = True
    else:
        data["metrics"]["retrieval_applicability"] = "not_applicable"
    with pytest.raises(reports.ReportError):
        reports.seal_run(tmp_path / "bad-summary", data)


@pytest.mark.parametrize(
    "change", ["all_success", "state_reallocation", "language_reallocation", "extra_metric"]
)
def test_v2_gate_recomputes_complete_raw_metrics_from_independent_dataset(tmp_path, change):
    data = raw_v2()
    dataset = v2_dataset(data)
    good = reports.seal_run(tmp_path / "good", data)
    assert check("inventory", good, dataset=dataset)["exit_code"] == 0
    group = data["metrics"]["groups"]["handbook"]
    if change == "all_success":
        group["replies"]["all"]["numerator"] -= 1
        group["replies"]["all"]["value"] = 27 / 28
    elif change == "state_reallocation":
        group["replies"]["state:answerable"] = ratio(27, 27)
        group["replies"]["state:unanswerable"] = ratio(1, 1)
    elif change == "language_reallocation":
        left, right = (group["replies"]["language:" + name] for name in ("zh", "en"))
        left["denominator"] -= 1
        left["planned_count"] -= 1
        right["denominator"] += 1
        right["planned_count"] += 1
    else:
        data["metrics"]["invented_accuracy"] = 1.0
    tampered = reports.seal_run(tmp_path / "structurally-consistent-but-wrong", data)
    result = check("inventory", tampered, dataset=dataset)
    assert result["exit_code"] == 3
    assert any("independently recomputed" in reason["message"] for reason in result["reasons"])


@pytest.mark.parametrize("mode", ["rule_only", "mocked_model"])
def test_v2_actual_dataset_runner_aggregation_seals_and_recomputes(tmp_path, mode):
    from lead_cleaner.answerability_evaluation.dataset import load_dataset
    from lead_cleaner.answerability_evaluation.metrics import score_retrieval

    dataset = load_dataset(Path(__file__).resolve().parents[1], PROTOCOL)
    data = raw_v2(mode)
    meta = data["metadata"]
    meta.update(
        {
            field: dataset[field]
            for field in (
                "dataset_hash",
                "knowledge_hash",
                "source_manifest_hash",
                "source_manifest",
            )
        }
    )
    meta["case_sources"] = {
        case["case_id"]: {
            field: case[field] for field in ("scenario_origin", "corpus_origin", "snapshot_id")
        }
        for case in dataset["cases"]
    }
    rebind(data)
    turns = {(c["case_id"], t["turn_id"]): t for c in dataset["cases"] for t in c["turns"]}
    for row in data["retrieval"]:
        row["metrics"] = score_retrieval(turns[(row["case_id"], row["turn_id"])], [])
    data["metrics"] = aggregate_metrics(
        dataset, data["observations"], data["assertions"], data["retrieval"], mode
    )
    run = reports.seal_run(tmp_path / mode, data)
    assert check("inventory", run, dataset=dataset)["exit_code"] == 0
    assert check("behavior", run, dataset=dataset, trust_context=v2_trust(run))["exit_code"] == 0
