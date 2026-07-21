import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from lead_cleaner.rag.eval_runner import (
    evaluate_match_detail,
    facet_recall_at_k,
    has_expected_match,
    has_expected_source,
    ndcg_at_k,
    reciprocal_rank,
    unjudged_rate_at_k,
    validate_eval_cases_against_chunks,
)
from lead_cleaner.rag.evaluation_report import load_eval_cases, sha256_file
from lead_cleaner.rag.knowledge_loader import load_knowledge_chunks
from lead_cleaner.rag.schemas import RetrievedChunk


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_REPORT_PATH = PROJECT_ROOT / "reports" / "rag-eval-bge-m3-v4-20260721.json"
DEFAULT_REVIEW_PATH = (
    PROJECT_ROOT / "data" / "rag_eval" / "review" / "bge-m3-v4-unjudged-review.json"
)
DEFAULT_EVAL_PATH = PROJECT_ROOT / "data" / "rag_eval" / "eval_queries.json"
DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "data" / "knowledge_snapshot" / "knowledge_chunks.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "reports" / "rag-eval-bge-m3-v4-reviewed-20260721.json"


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return payload


def _portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _metric_summary(*, top_1_hits: int, top_3_hits: int, total: int) -> dict[str, Any]:
    return {
        "top_1_hits": top_1_hits,
        "top_1_total": total,
        "top_1_hit_rate_percent": round(top_1_hits / total * 100, 2),
        "top_3_hits": top_3_hits,
        "top_3_total": total,
        "top_3_hit_rate_percent": round(top_3_hits / total * 100, 2),
    }


def _verify_review_is_applied(
    *,
    review_payload: dict[str, Any],
    eval_cases_by_id: dict[str, Any],
) -> None:
    items = review_payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Review file must contain a non-empty items list.")
    if review_payload.get("item_count") != len(items):
        raise ValueError("Review item_count does not match the items list length.")

    for item in items:
        if not isinstance(item, dict) or item.get("current_status") != "reviewed":
            raise ValueError("Every review item must be marked reviewed.")
        query_id = item.get("query_id")
        if not isinstance(query_id, str) or query_id not in eval_cases_by_id:
            raise ValueError(f"Unknown reviewed query_id: {query_id!r}.")
        review = item.get("review")
        if not isinstance(review, dict):
            raise ValueError(f"Review item {item.get('review_id')!r} has no decision.")
        matching = [
            judgment
            for judgment in eval_cases_by_id[query_id].judgments
            if judgment.source_title == item.get("source_title")
            and judgment.section == item.get("section")
        ]
        if len(matching) != 1:
            raise ValueError(
                f"Reviewed judgment {item.get('review_id')!r} is not applied exactly once."
            )
        judgment = matching[0]
        if (
            judgment.relevance_grade != review.get("relevance_grade")
            or list(judgment.covers_facets) != review.get("covers_facets")
            or judgment.reason != review.get("reason")
        ):
            raise ValueError(f"Applied judgment {item.get('review_id')!r} differs from the review.")


def _retrieved_chunks(
    *,
    report_case: dict[str, Any],
    chunks_by_id: dict[str, Any],
) -> list[RetrievedChunk]:
    sources = report_case.get("retrieved_sources")
    if not isinstance(sources, list) or len(sources) < 3:
        raise ValueError(f"Report case {report_case.get('query_id')!r} needs at least 3 results.")
    results: list[RetrievedChunk] = []
    seen_chunk_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Every retrieved source must be an object.")
        chunk_id = source.get("chunk_id")
        rank = source.get("rank")
        if not isinstance(chunk_id, str) or chunk_id not in chunks_by_id:
            raise ValueError(f"Unknown retrieved chunk_id: {chunk_id!r}.")
        if chunk_id in seen_chunk_ids:
            raise ValueError(f"Duplicate retrieved chunk_id: {chunk_id!r}.")
        seen_chunk_ids.add(chunk_id)
        chunk = chunks_by_id[chunk_id]
        if (
            source.get("source_title") != chunk.source_title
            or source.get("section") != chunk.section
        ):
            raise ValueError(f"Stored report metadata differs for chunk {chunk_id!r}.")
        results.append(
            RetrievedChunk.model_validate(
                {
                    **chunk.model_dump(mode="json"),
                    "score": 0.0,
                    "rank": rank,
                    "retrieval_source": "fusion",
                }
            )
        )
    return sorted(results, key=lambda result: result.rank)


def _rescore_evaluation(
    *,
    evaluation: dict[str, Any],
    eval_cases_by_id: dict[str, Any],
    chunks_by_id: dict[str, Any],
) -> dict[str, Any]:
    report_cases = evaluation.get("cases")
    if not isinstance(report_cases, list):
        raise ValueError("Each evaluation path must contain a cases list.")
    if len(report_cases) != len(eval_cases_by_id):
        raise ValueError("Stored report case count does not match the evaluation dataset.")

    direct_top_1_hits = 0
    direct_top_3_hits = 0
    source_top_1_hits = 0
    source_top_3_hits = 0
    reciprocal_ranks: list[float] = []
    ndcg_values: list[float] = []
    facet_recall_values: list[float] = []
    unjudged_rate_values: list[float] = []
    rescored_cases: list[dict[str, Any]] = []
    seen_query_ids: set[str] = set()

    for report_case in report_cases:
        if not isinstance(report_case, dict):
            raise ValueError("Every stored report case must be an object.")
        query_id = report_case.get("query_id")
        if not isinstance(query_id, str) or query_id not in eval_cases_by_id:
            raise ValueError(f"Unknown report query_id: {query_id!r}.")
        if query_id in seen_query_ids:
            raise ValueError(f"Duplicate report query_id: {query_id!r}.")
        seen_query_ids.add(query_id)
        eval_case = eval_cases_by_id[query_id]
        if report_case.get("input_query") != eval_case.query:
            raise ValueError(f"Stored input query differs for {query_id!r}.")
        results = _retrieved_chunks(report_case=report_case, chunks_by_id=chunks_by_id)

        direct_top_1_hit = has_expected_match(results, eval_case, top_k=1)
        direct_top_3_hit = has_expected_match(results, eval_case, top_k=3)
        source_top_1_hit = has_expected_source(results, eval_case, top_k=1)
        source_top_3_hit = has_expected_source(results, eval_case, top_k=3)
        case_reciprocal_rank = reciprocal_rank(results[:3], eval_case)
        case_ndcg = ndcg_at_k(results, eval_case, top_k=3)
        case_facet_recall = facet_recall_at_k(results, eval_case, top_k=3)
        case_unjudged_rate = unjudged_rate_at_k(results, eval_case, top_k=3)

        direct_top_1_hits += int(direct_top_1_hit)
        direct_top_3_hits += int(direct_top_3_hit)
        source_top_1_hits += int(source_top_1_hit)
        source_top_3_hits += int(source_top_3_hit)
        reciprocal_ranks.append(case_reciprocal_rank)
        ndcg_values.append(case_ndcg)
        facet_recall_values.append(case_facet_recall)
        unjudged_rate_values.append(case_unjudged_rate)

        rescored_case = dict(report_case)
        rescored_case.update(
            {
                "direct_top_1_hit": direct_top_1_hit,
                "direct_top_3_hit": direct_top_3_hit,
                "source_top_1_hit": source_top_1_hit,
                "source_top_3_hit": source_top_3_hit,
                "reciprocal_rank_at_3": round(case_reciprocal_rank, 4),
                "ndcg_at_3": round(case_ndcg, 4),
                "facet_recall_at_3": round(case_facet_recall, 4),
                "unjudged_rate_at_3": round(case_unjudged_rate, 4),
                "retrieved_sources": [
                    {
                        "chunk_id": result.chunk_id,
                        "source_title": result.source_title,
                        "section": result.section,
                        "rank": result.rank,
                        "relevance_grade": detail.relevance_grade,
                        "judged": detail.judged,
                        "relevant_match": detail.relevant_match,
                        "direct_match": detail.direct_match,
                        "source_match": detail.source_match,
                        "covers_facets": list(detail.covers_facets),
                    }
                    for result in results
                    for detail in [evaluate_match_detail(result, eval_case)]
                ],
            }
        )
        rescored_cases.append(rescored_case)

    total = len(eval_cases_by_id)
    rescored_evaluation = dict(evaluation)
    rescored_evaluation["metrics"] = {
        "source": _metric_summary(
            top_1_hits=source_top_1_hits,
            top_3_hits=source_top_3_hits,
            total=total,
        ),
        "direct": _metric_summary(
            top_1_hits=direct_top_1_hits,
            top_3_hits=direct_top_3_hits,
            total=total,
        ),
        "ranking": {
            "mean_reciprocal_rank_at_3": round(mean(reciprocal_ranks), 4),
            "mean_ndcg_at_3": round(mean(ndcg_values), 4),
            "mean_facet_recall_at_3": round(mean(facet_recall_values), 4),
            "mean_unjudged_rate_at_3": round(mean(unjudged_rate_values), 4),
        },
    }
    rescored_evaluation["cases"] = rescored_cases
    return rescored_evaluation


def rescore_report_from_stored_rankings(
    *,
    source_report_path: str | Path,
    review_path: str | Path,
    eval_path: str | Path,
    chunks_path: str | Path,
    output_path: str | Path,
    rescored_at: datetime | None = None,
) -> dict[str, Any]:
    source_report_path = Path(source_report_path)
    review_path = Path(review_path)
    eval_path = Path(eval_path)
    chunks_path = Path(chunks_path)
    output_path = Path(output_path)

    source_report = _load_json_object(source_report_path)
    review_payload = _load_json_object(review_path)
    if source_report.get("report_schema_version") != "rag-eval-v4":
        raise ValueError("Source report must use report_schema_version rag-eval-v4.")
    if source_report.get("dataset", {}).get("sha256") != review_payload.get("dataset_sha256"):
        raise ValueError("Source report does not match the reviewed dataset hash.")
    if source_report.get("knowledge_snapshot", {}).get("sha256") != review_payload.get(
        "knowledge_sha256"
    ):
        raise ValueError("Source report does not match the reviewed knowledge hash.")
    if sha256_file(chunks_path) != review_payload.get("knowledge_sha256"):
        raise ValueError("Current knowledge snapshot differs from the reviewed snapshot.")

    eval_cases = load_eval_cases(eval_path)
    chunks = load_knowledge_chunks(chunks_path)
    validate_eval_cases_against_chunks(eval_cases, chunks)
    eval_cases_by_id = {case.query_id: case for case in eval_cases}
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    _verify_review_is_applied(
        review_payload=review_payload,
        eval_cases_by_id=eval_cases_by_id,
    )

    evaluations = source_report.get("evaluations")
    if not isinstance(evaluations, dict) or not evaluations:
        raise ValueError("Source report does not contain evaluation paths.")
    rescored_evaluations = {
        path_name: _rescore_evaluation(
            evaluation=evaluation,
            eval_cases_by_id=eval_cases_by_id,
            chunks_by_id=chunks_by_id,
        )
        for path_name, evaluation in evaluations.items()
        if isinstance(evaluation, dict)
    }
    if set(rescored_evaluations) != set(evaluations):
        raise ValueError("Every evaluation path must be an object.")

    required_paths = {"raw_query", "runtime_rule_query", "runtime_fused_query"}
    if not required_paths.issubset(rescored_evaluations):
        raise ValueError("Source report is missing one or more required query paths.")
    raw = rescored_evaluations["raw_query"]["metrics"]["direct"]
    runtime = rescored_evaluations["runtime_rule_query"]["metrics"]["direct"]
    fused = rescored_evaluations["runtime_fused_query"]["metrics"]["direct"]

    rescored_report = dict(source_report)
    rescored_report["dataset"] = {
        "path": _portable_path(eval_path),
        "sha256": sha256_file(eval_path),
        "eval_case_count": len(eval_cases),
        "facet_count": sum(len(case.facets) for case in eval_cases),
        "judgment_count": sum(len(case.judgments) for case in eval_cases),
    }
    rescored_report["evaluations"] = rescored_evaluations
    comparison = dict(source_report.get("comparison", {}))
    comparison.update(
        {
            "runtime_minus_raw_top_1_hits": runtime["top_1_hits"] - raw["top_1_hits"],
            "runtime_minus_raw_top_3_hits": runtime["top_3_hits"] - raw["top_3_hits"],
            "fused_minus_raw_top_1_hits": fused["top_1_hits"] - raw["top_1_hits"],
            "fused_minus_raw_top_3_hits": fused["top_3_hits"] - raw["top_3_hits"],
            "fused_minus_feature_only_top_1_hits": (fused["top_1_hits"] - runtime["top_1_hits"]),
            "fused_minus_feature_only_top_3_hits": (fused["top_3_hits"] - runtime["top_3_hits"]),
        }
    )
    rescored_report["comparison"] = comparison
    bge_evaluation = dict(source_report.get("bge_evaluation", {}))
    bge_evaluation["note"] = (
        "Retrieval rankings come from the source BGE-M3 run; metrics were rescored "
        "offline against the expanded reviewed label pool."
    )
    rescored_report["bge_evaluation"] = bge_evaluation
    rescored_time = rescored_at or datetime.now(UTC)
    rescored_report["rescoring"] = {
        "status": "completed_from_stored_rankings",
        "rescored_at_utc": rescored_time.astimezone(UTC).isoformat(),
        "source_report": _portable_path(source_report_path),
        "source_dataset_sha256": review_payload["dataset_sha256"],
        "review_file": _portable_path(review_path),
        "reviewed_judgment_count": review_payload["item_count"],
        "retrieval_rerun": False,
        "network_access_required": False,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(rescored_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return rescored_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rescore stored RAG rankings against an expanded reviewed label pool.",
    )
    parser.add_argument("--source-report", type=Path, default=DEFAULT_SOURCE_REPORT_PATH)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW_PATH)
    parser.add_argument("--eval", type=Path, default=DEFAULT_EVAL_PATH)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = rescore_report_from_stored_rankings(
        source_report_path=args.source_report,
        review_path=args.review,
        eval_path=args.eval,
        chunks_path=args.chunks,
        output_path=args.output,
    )
    print(f"Rescored report: {args.output}")
    print(f"Judgments: {report['dataset']['judgment_count']}")
    for path_name, evaluation in report["evaluations"].items():
        ranking = evaluation["metrics"]["ranking"]
        print(
            f"{path_name}: nDCG@3 {ranking['mean_ndcg_at_3']}, "
            f"Unjudged@3 {ranking['mean_unjudged_rate_at_3']}"
        )


if __name__ == "__main__":
    main()
