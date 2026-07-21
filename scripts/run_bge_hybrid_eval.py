import argparse
from pathlib import Path

from lead_cleaner.rag.bge_embedding_provider import DEFAULT_BGE_EMBEDDING_MODEL
from lead_cleaner.rag.evaluation_report import (
    run_bge_evaluation,
    write_evaluation_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "data" / "knowledge_snapshot" / "knowledge_chunks.json"
DEFAULT_EVAL_QUERIES_PATH = PROJECT_ROOT / "data" / "rag_eval" / "eval_queries.json"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "rag-eval-bge-m3-v4-20260721.json"
DEFAULT_LOCAL_PROXY_URL = "http://127.0.0.1:8000/v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the v4 paired graded-relevance evaluation with BGE-M3.",
    )
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--queries", type=Path, default=DEFAULT_EVAL_QUERIES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--base-url", default=DEFAULT_LOCAL_PROXY_URL)
    parser.add_argument("--model", default=DEFAULT_BGE_EMBEDDING_MODEL)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args()


def _print_path_summary(path_label: str, evaluation: dict[str, object]) -> None:
    metrics = evaluation["metrics"]
    assert isinstance(metrics, dict)
    direct = metrics["direct"]
    ranking = metrics["ranking"]
    assert isinstance(direct, dict)
    assert isinstance(ranking, dict)
    print(
        f"{path_label}: Direct Top 1 "
        f"{direct['top_1_hits']}/{direct['top_1_total']}, "
        f"Top 3 {direct['top_3_hits']}/{direct['top_3_total']}, "
        f"MRR@3 {ranking['mean_reciprocal_rank_at_3']}, "
        f"nDCG@3 {ranking['mean_ndcg_at_3']}, "
        f"Facet Recall@3 {ranking['mean_facet_recall_at_3']}, "
        f"Unjudged@3 {ranking['mean_unjudged_rate_at_3']}"
    )


def _failed_top_3_query_ids(evaluation: dict[str, object]) -> list[str]:
    cases = evaluation["cases"]
    assert isinstance(cases, list)
    return [
        str(case["query_id"])
        for case in cases
        if isinstance(case, dict) and not case["direct_top_3_hit"]
    ]


def main() -> None:
    args = parse_args()
    report = run_bge_evaluation(
        chunks_path=args.chunks,
        eval_queries_path=args.queries,
        base_url=args.base_url,
        model_name=args.model,
        timeout=args.timeout,
    )
    write_evaluation_report(report, args.output)

    evaluations = report["evaluations"]
    raw_evaluation = evaluations["raw_query"]
    rule_evaluation = evaluations["runtime_rule_query"]
    fused_evaluation = evaluations["runtime_fused_query"]

    print(f"Report: {args.output}")
    print(f"Model: {report['retrieval']['embedding_provider']}")
    print(f"Dataset SHA-256: {report['dataset']['sha256']}")
    print(f"Knowledge SHA-256: {report['knowledge_snapshot']['sha256']}")
    print(f"Label contract: {report['label_contract_version']}")
    _print_path_summary("Raw query", raw_evaluation)
    _print_path_summary("Runtime rule query", rule_evaluation)
    _print_path_summary("Runtime fused query", fused_evaluation)
    print(f"Raw Top-3 failures: {_failed_top_3_query_ids(raw_evaluation)}")
    print(f"Fused Top-3 failures: {_failed_top_3_query_ids(fused_evaluation)}")


if __name__ == "__main__":
    main()
