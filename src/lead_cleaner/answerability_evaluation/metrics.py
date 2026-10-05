"""Fixed-cohort answerability metrics, with explicit unknown and N/A states."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


def ratio(
    numerator: float,
    denominator: int,
    *,
    unknown: int = 0,
    errors: int = 0,
    not_run: int = 0,
    planned: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    incomplete = bool(unknown or errors or not_run)
    applicability = (
        "incomplete_judgments" if incomplete else "applicable" if denominator else "not_applicable"
    )
    return {
        "applicability": applicability,
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator and not incomplete else None,
        "planned_count": denominator if planned is None else planned,
        "adjudicated_count": max(0, denominator - unknown - errors - not_run),
        "error_count": errors,
        "not_run_count": not_run,
        "needs_review_count": unknown,
        "excluded_by_design": 0,
        "reason": reason if reason else ("zero_denominator" if not denominator else None),
    }


def required_answerable(turn: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in turn["facets"] if f["required"] and f["answerable"]]


def supported_facets(turn: dict[str, Any], chunk_ids: set[str]) -> set[str]:
    return {
        f["facet_id"]
        for f in required_answerable(turn)
        if any(set(group) <= chunk_ids for group in f["support_groups"])
    }


def score_retrieval(
    turn: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    k: int = 3,
    execution_status: str = "completed",
) -> dict[str, Any]:
    """Truncate before deduplication; no promoted fourth-ranked evidence."""
    if k <= 0:
        raise ValueError("K must be positive")
    facets = required_answerable(turn)
    labels = turn["judgments"]
    window = results[:k]
    identifiers = [r["chunk_id"] for r in window]
    unknown = sum(chunk_id not in labels for chunk_id in identifiers)
    error, not_run = int(execution_status == "error"), int(execution_status == "not_run")
    covered = supported_facets(turn, set(identifiers))
    rr = next(
        (
            1 / rank
            for rank in range(1, len(window) + 1)
            if supported_facets(turn, set(identifiers[:rank]))
        ),
        0.0,
    )
    unresolved = int(bool(unknown and not covered))
    values = {
        "supported_facet_hit": ratio(
            int(bool(covered)),
            int(bool(facets)),
            unknown=unresolved if facets else 0,
            errors=error,
            not_run=not_run,
        ),
        "support_completion_rr": ratio(
            rr,
            int(bool(facets)),
            unknown=int(
                any(
                    identifier not in labels
                    for identifier in identifiers[
                        : int(round(1 / rr)) - 1 if rr else len(identifiers)
                    ]
                )
            )
            if facets
            else 0,
            errors=error,
            not_run=not_run,
        ),
        "answerable_facet_recall": ratio(
            len(covered),
            len(facets),
            unknown=(len(facets) - len(covered)) if unknown else 0,
            errors=error,
            not_run=not_run,
        ),
        "unjudged_rate": ratio(
            unknown,
            len(window),
            errors=error,
            not_run=not_run,
            reason="empty_retrieval" if not window else None,
        ),
    }
    ideal = sorted(labels.values(), reverse=True)[:k]
    idcg = sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal, 1))
    seen: set[str] = set()
    dcg = 0.0
    for rank, chunk_id in enumerate(identifiers, 1):
        if chunk_id not in seen and chunk_id in labels:
            dcg += (2 ** labels[chunk_id] - 1) / math.log2(rank + 1)
        seen.add(chunk_id)
    applicable = bool(facets and idcg > 0)
    ndcg = ratio(
        dcg / idcg if applicable else 0.0,
        int(applicable),
        unknown=int(bool(unknown)) if applicable else 0,
        errors=error,
        not_run=not_run,
        reason="no_required_answer_or_zero_idcg" if not applicable else None,
    )
    ndcg.update(dcg=dcg if not unknown else None, idcg=idcg, top_k=k)
    values["ndcg"] = ndcg
    values["answerable_facet_recall"]["covered_facets"] = sorted(covered)
    return values


def summarize_retrieval(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_path[row["path"]].append(row)
    summary: dict[str, Any] = {}
    for path, items in sorted(by_path.items()):
        output: dict[str, Any] = {}
        for name in (
            "supported_facet_hit",
            "support_completion_rr",
            "answerable_facet_recall",
            "ndcg",
            "unjudged_rate",
        ):
            metrics = [row["metrics"][name] for row in items]
            output[name] = ratio(
                sum(m["numerator"] for m in metrics),
                sum(m["denominator"] for m in metrics),
                unknown=sum(m["needs_review_count"] for m in metrics),
                errors=sum(m["error_count"] for m in metrics),
                not_run=sum(m["not_run_count"] for m in metrics),
            )
            output[name]["excluded_by_design"] = sum(
                m["applicability"] == "not_applicable" for m in metrics
            )
            if name == "answerable_facet_recall":
                eligible = [m for m in metrics if m["denominator"]]
                output["answerable_facet_recall_macro"] = ratio(
                    sum(m["value"] or 0 for m in eligible),
                    len(eligible),
                    unknown=sum(m["value"] is None for m in eligible),
                )
        summary[path] = output
    return summary


def task_ratio(
    successes: int, planned: int, *, errors: int = 0, not_run: int = 0, unknown: int = 0
) -> dict[str, Any]:
    """Execution failure remains in task denominators; unknown semantics stays null."""
    result = ratio(successes, planned, unknown=unknown)
    result.update(
        error_count=errors,
        not_run_count=not_run,
        adjudicated_count=max(0, planned - errors - not_run - unknown),
        conclusion="provisional" if unknown else "measured",
    )
    return result


def summarize_replies(
    dataset: dict[str, Any], observations: list[dict[str, Any]], assertions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Keep turn, facet and claim coverage separate; never equate errors with refusal."""
    observed = {(o["case_id"], o["turn_id"]): o for o in observations}
    graded: dict[tuple[str, str], dict[str, Any]] = defaultdict(dict)
    for assertion in assertions:
        graded[(assertion["case_id"], assertion["turn_id"])][assertion["assertion_id"]] = assertion
    bins: dict[str, list[dict[str, Any]]] = defaultdict(list)
    totals: dict[str, int] = defaultdict(int)
    for case in dataset["cases"]:
        case_success, case_unknown = True, False
        for turn in case["turns"]:
            key = (case["case_id"], turn["turn_id"])
            obs, checks = observed.get(key, {}), graded.get(key, {})
            execution = obs.get("execution_status", "not_run")
            executed = execution == "completed"
            pending = executed and (
                len(checks) != 5
                or any(a["behavior_status"] == "needs_review" for a in checks.values())
            )
            passed = (
                executed
                and len(checks) == 5
                and all(a["behavior_status"] == "pass" for a in checks.values())
            )
            status = {
                "success": passed,
                "error": execution == "error",
                "not_run": execution == "not_run",
                "needs_review": pending,
            }
            dimensions = [
                "all",
                "state:" + turn["answerability"],
                "language:" + case["language"],
                "turns:" + ("multi" if len(case["turns"]) > 1 else "single"),
            ]
            dimensions.extend(
                "reason:" + r
                for r in sorted(
                    {reason for f in turn["facets"] if f["required"] for reason in f["reasons"]}
                )
            )
            for dimension in dimensions:
                bins[dimension].append(status)
            case_success = case_success and passed
            case_unknown = case_unknown or pending
            facets = len(required_answerable(turn))
            totals["facets"] += facets
            totals["facet_errors"] += facets if execution == "error" else 0
            totals["facet_not_run"] += facets if execution == "not_run" else 0
            totals["facet_unknown"] += facets if pending else 0
            detail = checks.get("answer_content", {}).get("details", {})
            totals["answered_facets"] += (
                len(detail.get("answered_required_facets", [])) if executed else 0
            )
            claims_detail = checks.get("grounding", {}).get("details", {})
            complete = claims_detail.get("claims_complete") is True
            claims = claims_detail.get("claims", [])
            bad = any(c["verdict"] in {"unsupported", "contradicted"} for c in claims)
            if execution == "error" and obs.get("api_status") == 200 and obs.get("reply_text"):
                totals["fallbacks"] += 1
                totals["reviewed_fallbacks"] += int(complete)
                totals["safe_fallbacks"] += int(complete and not bad)
            if not executed or not complete:
                continue
            totals["reviewed_turns"] += 1
            totals["answered_turns"] += int(bool(claims))
            totals["unsupported_turns"] += int(bad)
            totals["claims"] += len(claims)
            totals["cited_supported_claims"] += sum(
                c.get("citation_supported") is True for c in claims
            )
            available = set(detail.get("context_supported_facets", []))
            totals["context_facets"] += len(available)
            totals["context_omitted"] += len(
                available - set(detail.get("addressed_required_facets", []))
            )
            totals["context_turns"] += int(bool(available))
            totals["unnecessary_refusals"] += int(
                bool(available) and detail.get("reply_action") == "full_refusal"
            )
        totals["conversation_success"] += int(case_success)
        totals["conversation_unknown"] += int(case_unknown)
    result: dict[str, Any] = {}
    for name, items in bins.items():
        result[name] = task_ratio(
            sum(i["success"] for i in items),
            len(items),
            errors=sum(i["error"] for i in items),
            not_run=sum(i["not_run"] for i in items),
            unknown=sum(i["needs_review"] for i in items),
        )
    planned = sum(len(c["turns"]) for c in dataset["cases"])
    result.update(
        end_to_end_facet_recall=task_ratio(
            totals["answered_facets"],
            totals["facets"],
            errors=totals["facet_errors"],
            not_run=totals["facet_not_run"],
            unknown=totals["facet_unknown"],
        ),
        unsupported_answer_rate=ratio(totals["unsupported_turns"], totals["answered_turns"]),
        citation_support_rate=ratio(totals["cited_supported_claims"], totals["claims"]),
        context_supported_omission_rate=ratio(totals["context_omitted"], totals["context_facets"]),
        unnecessary_full_refusal_rate=ratio(
            totals["unnecessary_refusals"], totals["context_turns"]
        ),
        adjudication_coverage=ratio(totals["reviewed_turns"], planned),
        answer_coverage=ratio(totals["answered_turns"], planned),
        conversation_success=task_ratio(
            totals["conversation_success"],
            len(dataset["cases"]),
            unknown=totals["conversation_unknown"],
        ),
        fallback_safety=ratio(totals["safe_fallbacks"], totals["reviewed_fallbacks"]),
        fallback_adjudication_coverage=ratio(totals["reviewed_fallbacks"], totals["fallbacks"]),
        predicted_answerability={"applicability": "not_observed", "value": None},
        unadjudicated_turns=planned - totals["reviewed_turns"],
    )
    return result
