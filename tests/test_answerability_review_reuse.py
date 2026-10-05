"""Strict semantic equality and authority tests; all reviewer identities are unit fixtures."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from lead_cleaner.answerability_evaluation import checks, reports, review_reuse, trust
from lead_cleaner.answerability_evaluation.adapters import run_observations
from lead_cleaner.answerability_evaluation.dataset import load_dataset, text_hash
from lead_cleaner.answerability_evaluation.metrics import score_retrieval
from lead_cleaner.answerability_evaluation.retrieval import run_retrieval

ROOT = Path(__file__).resolve().parents[1]


def semantic_case(tmp_path, verdict="pass", mode="mocked_model", auto_failure=False):
    """Real API-shaped reports with synthetic unit-only human authority, never published."""
    source = load_dataset(ROOT)
    chunk = deepcopy(source["snapshots"]["core"]["chunks"][0]["chunk"])
    text = "A 30% deposit is payable after written confirmation."
    chunk.update(chunk_id="payment", section="Payment Conditions", doc_type="faq", text=text)
    snapshot = {
        "snapshot_id": "unit",
        "synthetic": True,
        "chunks": [
            {
                "chunk": chunk,
                "sha256": text_hash(text),
                "valid_from": None,
                "valid_to": None,
                "validity_basis": "evaluation_time",
            }
        ],
    }
    turn = {
        "turn_id": "T1",
        "message": "We plan to visit Yunnan. What are the payment terms?",
        "evaluation_time": "2026-10-05T00:00:00+00:00",
        "business_date": "2026-10-05",
        "answerability": "answerable",
        "expected_facts": [],
        "expected_state": None,
        "judgments": {"payment": 3},
        "facets": [
            {
                "facet_id": "payment",
                "required": True,
                "answerable": True,
                "support_groups": [["payment"]],
                "reasons": [],
            }
        ],
    }
    if auto_failure:
        turn["expected_facts"] = [
            {
                "key": "group_size",
                "value": "8",
                "statuses": ["customer_confirmed"],
                "source_turn_id": "T1",
            }
        ]
    dataset = {
        "protocol_id": "p0-02.v1",
        "dataset_hash": "unit-dataset",
        "knowledge_hash": "unit-knowledge",
        "cases": [{"case_id": "AB01", "snapshot_id": "unit", "language": "en", "turns": [turn]}],
        "snapshots": {"unit": snapshot},
    }
    metadata = {
        "schema_version": "answerability-eval.v1",
        "protocol_id": "p0-02.v1",
        "mode": mode,
        "protocol_hash": "unit-protocol",
        "dataset_hash": dataset["dataset_hash"],
        "knowledge_hash": dataset["knowledge_hash"],
        "evaluator_hash": "unit-evaluator",
        "rubric_hash": "unit-rubric",
        "environment_hash": "unit-environment",
        "code_hash": "unit-code",
        "real_model_calls": 0,
        "provisional": False,
        "source_dirty": False,
        "business_labels_reviewed": True,
        "review_required_roles": ["developer", "sales"],
        "expected_keys": checks.expected_keys(dataset, mode),
        "expected_retrieval_keys": checks.expected_retrieval_keys(dataset, mode),
    }
    retrieval = run_retrieval(dataset) if mode == "rule_only" else []
    for row in retrieval:
        row["metrics"] = score_retrieval(turn, row["results"], k=3)
    runs = []
    for name, sha in (("baseline", "a" * 40), ("candidate", "b" * 40)):
        observations = run_observations(ROOT, dataset, mode, tmp_path / (name + "-work"))
        raw = {
            "metadata": {**metadata, "tested_commit": sha},
            "observations": observations,
            "assertions": checks.evaluate_assertions(dataset, observations),
            "retrieval": retrieval,
            "metrics": {"purpose": "unit fixture"},
        }
        runs.append(reports.seal_run(tmp_path / name, raw))
    baseline, candidate = runs
    observation = baseline["observations"][0]
    start = observation["reply_text"].index(text)
    semantic = {
        "observation_hash": reports.content_hash(observation),
        "rubric_version": checks.RUBRIC,
        "claims_complete": True,
        "completeness_rationale": "Unit fixture: the only knowledge claim is the deposit condition; the remainder records customer facts and asks follow-up questions.",
        "claims": [
            {
                "claim_id": "deposit",
                "start": start,
                "end": start + len(text),
                "text": text,
                "proposition": text,
                "rationale": "The source states exactly this conditional amount.",
                "facet_id": "payment",
                "verdict": "supported",
                "review_status": "reviewed",
                "evidence_refs": [
                    {
                        "chunk_id": "payment",
                        "sha256": text_hash(text),
                        "start": 0,
                        "end": len(text),
                        "quote": text,
                    }
                ],
            }
        ],
        "answered_facets": ["payment"],
        "reply_action": "answer",
        "action_appropriate": verdict == "pass",
        "gap_disclosed": True,
        "clarification_appropriate": True,
    }
    assessed = checks.score_observation(turn, snapshot, observation, semantic)
    review = {"review_set_id": "unit-reviewed", "reviews": []}
    for row in assessed:
        if row["assertion_id"] not in review_reuse.SEMANTIC_ASSERTIONS:
            continue
        for role in ("developer", "sales"):
            review["reviews"].append(
                {
                    "review_id": row["assertion_id"] + "-" + role,
                    "key": list(reports.key(row)),
                    "run_manifest_hash": baseline["manifest_hash"],
                    "output_hash": row["observation_hash"],
                    "rubric_hash": metadata["rubric_hash"],
                    "reviewer": "unit-fixture-" + role,
                    "role": role,
                    "reason": "Synthetic unit test authority only",
                    "reviewed_at": "2026-10-05T00:00:00Z",
                    "verdict": row["behavior_status"],
                    "failure_type": row["failure_type"],
                    "semantic": deepcopy(semantic),
                }
            )
    issue_fields = tuple(f for f in reports.KEY_FIELDS if f != "trial_id") + (
        "failure_type",
        "severity",
    )
    issues = [
        {
            "issue_id": "unit-issue-" + row["assertion_id"],
            "status": "open",
            **{field: row[field] for field in issue_fields},
        }
        for row in assessed
        if row["behavior_status"] == "fail"
    ]
    record = {
        "acceptance_id": "unit-accepted",
        "manifest_hash": baseline["manifest_hash"],
        "run": baseline,
        "review_set": review,
        "review_set_hash": reports.content_hash(review),
        "known_issues": issues,
        "known_issues_hash": reports.content_hash(issues),
    }
    context = {
        "protocol_id": "p0-02.v1",
        "accepted_baselines": {"unit-accepted": baseline["manifest_hash"]},
        "latest_accepted_baselines": {mode: "unit-accepted"},
        "accepted_review_set_hashes": [reports.content_hash(review)],
        "known_issues_hash": reports.content_hash(issues),
    }
    return {
        "baseline": baseline,
        "candidate": candidate,
        "record": record,
        "trust": context,
        "dataset": dataset,
        "reviews": review,
        "issues": issues,
    }


def reuse(case, rows=None):
    return review_reuse.reuse_reviewed_assertions(
        case["baseline"],
        case["record"],
        case["candidate"],
        rows if rows is not None else case["candidate"]["assertions"],
        case["trust"],
        case["dataset"],
    )


def reseal(case, tmp_path, transform, *, source=False):
    name = "baseline" if source else "candidate"
    data = deepcopy(case[name])
    transform(data)
    for row in data["assertions"]:
        observation = next(
            o
            for o in data["observations"]
            if reports.key(o, reports.OBSERVATION_FIELDS)
            == reports.key(row, reports.OBSERVATION_FIELDS)
        )
        row["observation_hash"] = reports.content_hash(observation)
    result = reports.seal_run(tmp_path, data)
    case[name] = result
    return result


@pytest.mark.parametrize("mode", ["rule_only", "mocked_model"])
def test_equivalent_real_api_runs_reuse_only_reviewed_semantics(tmp_path, mode):
    case = semantic_case(tmp_path, mode=mode)
    before = deepcopy(case)
    assert (
        case["baseline"]["observations"][0]["message_id_map"]
        != case["candidate"]["observations"][0]["message_id_map"]
    )
    rows, derived = reuse(case)
    assert all(row["behavior_status"] == "pass" for row in rows)
    assert len(derived) == 3
    assert {row["key"][-2] for row in derived} == review_reuse.SEMANTIC_ASSERTIONS
    assert all(row["algorithm"] == "semantic-fingerprint.v1" for row in derived)
    assert all(row["source_manifest_hash"] == case["baseline"]["manifest_hash"] for row in derived)
    assert all(
        row["candidate_manifest_hash"] == case["candidate"]["manifest_hash"] for row in derived
    )
    assert all("review_ids" not in row for row in rows)
    assert all(len(row["source_review_ids"]) == 2 for row in derived)
    assert case == before
    assert all(
        row["behavior_status"] == "needs_review"
        for row in reports.load_run(case["candidate"]["directory"])["assertions"]
        if row["manual_review"]
    )


@pytest.fixture
def case(tmp_path):
    return semantic_case(tmp_path)


def test_only_named_runtime_noise_is_ignored(case, tmp_path):
    def noise(run):
        run["metadata"].update(tested_commit="c" * 40, code_hash="changed-product-code")
        obs = run["observations"][0]
        obs.update(duration_ms=12.5, request_id="new-trace-id")
        obs["network_guard"]["loopback_connections"] += 7
        obs["response"]["current_analysis"]["analysis_id"] = "analysis-new-id"
        for stage in obs["stages"]:
            stage["duration_ms"] = 9
        for call in obs["model_calls"] + obs["retrieval_calls"]:
            call["duration_ms"] = 8

    reseal(case, tmp_path / "noise", noise)
    rows, derived = reuse(case)
    assert len(derived) == 3 and all(r["behavior_status"] == "pass" for r in rows)


@pytest.mark.parametrize(
    "change",
    [
        "reply",
        "display",
        "html",
        "source_ids",
        "evidence",
        "product",
        "context",
        "context_rule",
        "context_model",
        "history",
        "fact_value",
        "fact_status",
        "fact_source",
        "future_source",
        "missing_context",
        "new_observer_field",
        "new_response_field",
        "new_call_field",
        "system_prompt",
        "model_response",
        "model_source",
        "stage_skip",
        "fallback",
        "failed_stage",
        "unknown_stage",
        "missing_stage",
        "guard_external",
        "guard_new_field",
        "wrong_conversation",
        "bad_lead_id",
        "bad_timing",
        "raw_text_id",
        "reply_language",
        "model_call_missing",
    ],
)
def test_any_changed_or_unproved_business_evidence_remains_unreviewed(case, tmp_path, change):
    def mutate(run):
        import json

        obs = run["observations"][0]
        draft = obs["response"]["reply_draft"]
        if change in {"reply", "raw_text_id"}:
            suffix = " Changed." if change == "reply" else " conv_looks_like_an_internal_id"
            obs["reply_text"] += suffix
            draft["body_text"] += suffix
            draft["display_text"] += suffix
        elif change == "display":
            draft["display_text"] += " Guaranteed rooms."
        elif change == "html":
            draft["body_html"] = "<p>Guaranteed rooms</p>"
        elif change == "source_ids":
            draft["source_ids"] = []
        elif change == "evidence":
            draft["evidence"][0]["supporting_quote"] += " Guaranteed."
        elif change == "product":
            draft["recommended_products"] = [{"unexpected_product": "Guaranteed package"}]
        elif change.startswith("context"):
            field = "provided_context" + change.removeprefix("context")
            obs[field] = []
        elif change == "history":
            obs["history"] = ["Different previous customer requirement"]
        elif change.startswith("fact_"):
            field, value = {
                "fact_value": ("value", "Tibet"),
                "fact_status": ("status", "pending"),
                "fact_source": ("source_message_id", "unobserved-message"),
            }[change]
            obs["facts"][0][field] = value
            obs["response"]["confirmed_facts"][0][field] = value
        elif change == "future_source":
            obs["message_id_map"]["T2"] = "future-message"
        elif change == "missing_context":
            del obs["provided_context_rule"]
        elif change == "new_observer_field":
            obs["unexpected_business_state"] = "new"
        elif change == "new_response_field":
            obs["response"]["unexpected_business_state"] = "new"
        elif change == "new_call_field":
            obs["model_calls"][0]["unknown_decision"] = True
        elif change == "system_prompt":
            obs["model_calls"][0]["request"]["messages"][0]["content"] += " Changed policy."
        elif change == "model_response":
            obs["model_calls"][0]["response"] = {"updates": [{"hidden_behavior": "changed"}]}
        elif change == "model_source":
            message = obs["model_calls"][1]["request"]["messages"][1]
            payload = json.loads(message["content"])
            payload["current_facts"][0]["source_message_id"] = "unobserved-message"
            message["content"] = json.dumps(payload)
        elif change == "stage_skip":
            obs["stages"][1]["expected_to_run"] = False
        elif change == "fallback":
            obs["stages"][1]["fallback_used"] = True
        elif change == "failed_stage":
            obs["stages"][1]["provider_execution"] = "error"
        elif change == "unknown_stage":
            obs["stages"][1]["new_interpretation"] = True
        elif change == "missing_stage":
            obs["stages"].pop()
        elif change == "guard_external":
            obs["network_guard"]["external_blocked"] = 1
        elif change == "guard_new_field":
            obs["network_guard"]["secret_network_path"] = True
        elif change == "wrong_conversation":
            draft["conversation_id"] = "another-conversation"
        elif change == "bad_lead_id":
            obs["response"]["current_analysis"]["cleaned_lead"]["lead_id"] = "unrelated-lead"
        elif change == "bad_timing":
            obs["duration_ms"] = -1
        elif change == "reply_language":
            obs["response"]["reply_language"] = "zh"
        elif change == "model_call_missing":
            obs["model_calls"].pop()

    reseal(case, tmp_path / "changed", mutate)
    rows, derived = reuse(case)
    assert not derived
    assert all(r["behavior_status"] == "needs_review" for r in rows if r["manual_review"])


def test_source_map_must_be_bijective_and_cannot_collapse_two_real_turns(case):
    run = deepcopy(case["candidate"])
    obs = run["observations"][0]
    dataset = deepcopy(case["dataset"])
    second = {**dataset["cases"][0]["turns"][0], "turn_id": "T2"}
    dataset["cases"][0]["turns"].append(second)
    obs["turn_id"] = "T2"
    obs["message_id_map"]["T2"] = obs["message_id_map"]["T1"]
    with pytest.raises(review_reuse.NonReusableObservation):
        review_reuse.semantic_fingerprint(run, obs, dataset)


@pytest.mark.parametrize(
    "field",
    [
        "protocol_hash",
        "dataset_hash",
        "knowledge_hash",
        "rubric_hash",
        "evaluator_hash",
        "environment_hash",
    ],
)
def test_frozen_inputs_cannot_cross_review_boundaries(case, tmp_path, field):
    reseal(
        case, tmp_path / "changed-input", lambda run: run["metadata"].update({field: "different"})
    )
    with pytest.raises(reports.ReportError, match="frozen"):
        reuse(case)


def test_fixed_dates_are_part_of_semantic_fingerprint(case):
    candidate, data = case["candidate"], deepcopy(case["dataset"])
    obs = candidate["observations"][0]
    initial = review_reuse.semantic_fingerprint(candidate, obs, data)
    data["cases"][0]["turns"][0]["evaluation_time"] = "2027-01-01T00:00:00+00:00"
    changed = review_reuse.semantic_fingerprint(candidate, obs, data)
    assert changed != initial
    data["cases"][0]["turns"][0]["business_date"] = "2027-01-01"
    assert review_reuse.semantic_fingerprint(candidate, obs, data) != changed


@pytest.mark.parametrize(
    "target",
    [
        "latest",
        "accepted",
        "record_manifest",
        "source_manifest",
        "review_approval",
        "review_binding",
        "dataset",
        "case_keys",
        "candidate_keys",
    ],
)
def test_trust_and_identity_failures_never_become_reusable_authority(case, target):
    if target == "latest":
        case["trust"]["latest_accepted_baselines"] = {}
    elif target == "accepted":
        case["trust"]["accepted_baselines"] = {}
    elif target == "record_manifest":
        case["record"]["manifest_hash"] = "not-the-original"
    elif target == "source_manifest":
        case["baseline"]["manifest_hash"] = "not-the-original"
    elif target == "review_approval":
        case["trust"]["accepted_review_set_hashes"] = []
    elif target == "review_binding":
        case["record"]["review_set_hash"] = "different-review-set"
    elif target == "dataset":
        case["dataset"]["dataset_hash"] = "different-data"
    elif target == "case_keys":
        case["dataset"]["cases"][0]["case_id"] = "AB02"
    elif target == "candidate_keys":
        case["candidate"]["assertions"] = case["candidate"]["assertions"][:-1]
    with pytest.raises(reports.ReportError):
        reuse(case)


def approve_modified_fixture_reviews(case):
    digest = reports.content_hash(case["reviews"])
    case["trust"]["accepted_review_set_hashes"] = [digest]
    case["record"]["review_set_hash"] = digest


@pytest.mark.parametrize("change", ["one_role", "same_person", "conflict", "pending"])
def test_unresolved_or_nonindependent_original_humans_cannot_supply_proof(case, change):
    reviews = case["reviews"]["reviews"]
    if change == "one_role":
        case["reviews"]["reviews"] = [r for r in reviews if r["role"] == "developer"]
    elif change == "same_person":
        for review in reviews:
            review["reviewer"] = "one-real-person"
    elif change == "conflict":
        for review in reviews:
            if review["role"] == "sales":
                review["verdict"] = "fail"
    else:
        for review in reviews:
            review["verdict"] = "needs_review"
    approve_modified_fixture_reviews(case)
    rows, derived = reuse(case)
    assert not derived
    assert all(row["behavior_status"] == "needs_review" for row in rows if row["manual_review"])


def test_current_partial_or_disputed_human_work_is_never_overridden(case):
    rows = deepcopy(case["candidate"]["assertions"])
    for row in rows:
        if row["manual_review"]:
            row["review_ids"] = ["current-partial-review"]
    after, derived = reuse(case, rows)
    assert after == rows and not derived


def test_existing_current_verdicts_and_derived_records_are_not_replaced(case):
    rows, records = reuse(case)
    assert records
    again, records = reuse(case, rows)
    assert again == rows and not records
    pending = deepcopy(case["candidate"]["assertions"])
    for row in pending:
        if row["manual_review"]:
            row["derived_from"] = {"already": "present"}
    again, records = reuse(case, pending)
    assert again == pending and not records


def test_legacy_automatic_pass_without_human_evidence_is_not_reusable(case, tmp_path):
    def auto_pass(run):
        for row in run["assertions"]:
            if row["manual_review"]:
                row["behavior_status"] = "pass"
                row["manual_review"] = False

    baseline = reseal(case, tmp_path / "auto-source", auto_pass, source=True)
    case["record"].update(
        run=baseline,
        manifest_hash=baseline["manifest_hash"],
        review_set=trust.EMPTY_REVIEW_SET,
        review_set_hash=reports.content_hash(trust.EMPTY_REVIEW_SET),
    )
    case["trust"]["accepted_baselines"]["unit-accepted"] = baseline["manifest_hash"]
    rows, derived = reuse(case)
    assert not derived and all(
        r["behavior_status"] == "needs_review" for r in rows if r["manual_review"]
    )


def test_original_human_fail_is_preserved_as_the_same_failure(tmp_path):
    case = semantic_case(tmp_path, verdict="fail")
    rows, derived = reuse(case)
    failed = next(row for row in rows if row["assertion_id"] == "answer_content")
    assert (
        failed["behavior_status"] == "fail" and failed["failure_type"] == "answer_scope_or_omission"
    )
    assert len(derived) == 3


def test_exact_approved_historical_auto_failure_does_not_block_independent_semantics(tmp_path):
    case = semantic_case(tmp_path, auto_failure=True)
    rows, derived = reuse(case)
    fact_before = next(
        r for r in case["candidate"]["assertions"] if r["assertion_id"] == "facts_state"
    )
    assert fact_before["behavior_status"] == "fail"
    assert next(r for r in rows if r["assertion_id"] == "facts_state") == fact_before
    assert len(derived) == 3 and all(
        r["behavior_status"] == "pass" for r in rows if r["manual_review"]
    )


@pytest.mark.parametrize(
    "change", ["unknown", "resolved", "hash", "signature", "new_auto_failure", "execution"]
)
def test_automatic_failures_require_exact_original_open_issue(tmp_path, change):
    case = semantic_case(tmp_path, auto_failure=change != "new_auto_failure")
    if change == "unknown":
        case["record"]["known_issues"] = []
        case["record"]["known_issues_hash"] = reports.content_hash([])
    elif change == "resolved":
        case["record"]["known_issues"][0]["status"] = "resolved"
        case["record"]["known_issues_hash"] = reports.content_hash(case["record"]["known_issues"])
    elif change == "hash":
        case["record"]["known_issues_hash"] = "wrong"
    elif change == "signature":
        case["record"]["known_issues"][0]["failure_type"] = "other"
        case["record"]["known_issues_hash"] = reports.content_hash(case["record"]["known_issues"])
    else:

        def fail(run):
            row = next(
                r
                for r in run["assertions"]
                if r["assertion_id"] == ("execution" if change == "execution" else "facts_state")
            )
            row.update(behavior_status="fail", failure_type="new_failure")

        reseal(case, tmp_path / "new-auto-failure", fail)
    rows, derived = reuse(case)
    assert not derived and all(
        r["behavior_status"] == "needs_review" for r in rows if r["manual_review"]
    )


def test_effective_automatic_row_cannot_be_manually_rewritten(case):
    rows = deepcopy(case["candidate"]["assertions"])
    next(r for r in rows if r["assertion_id"] == "facts_state")["severity"] = "critical"
    after, derived = reuse(case, rows)
    assert after == rows and not derived


def test_reuse_rechecks_original_sealed_bytes(case):
    path = Path(case["baseline"]["directory"]) / "observations.jsonl"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(reports.ReportError):
        reuse(case)
