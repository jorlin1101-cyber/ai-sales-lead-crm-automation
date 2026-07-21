import argparse
from pathlib import Path

from lead_cleaner.rag.evaluation_report import (
    run_keyword_evaluation,
    write_evaluation_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "data" / "knowledge_snapshot" / "knowledge_chunks.json"
DEFAULT_EVAL_QUERIES_PATH = PROJECT_ROOT / "data" / "rag_eval" / "eval_queries.json"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "rag-eval-v4-20260721.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen offline keyword-RRF evaluation.",
    )
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--queries", type=Path, default=DEFAULT_EVAL_QUERIES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_keyword_evaluation(
        chunks_path=args.chunks,
        eval_queries_path=args.queries,
    )
    write_evaluation_report(report, args.output)

    raw_metrics = report["evaluations"]["raw_query"]["metrics"]
    runtime_metrics = report["evaluations"]["runtime_rule_query"]["metrics"]
    fused_metrics = report["evaluations"]["runtime_fused_query"]["metrics"]
    raw_direct = raw_metrics["direct"]
    raw_source = raw_metrics["source"]
    runtime_direct = runtime_metrics["direct"]
    runtime_source = runtime_metrics["source"]
    fused_direct = fused_metrics["direct"]
    fused_source = fused_metrics["source"]
    print(f"Report: {args.output}")
    print(f"Total eval cases: {raw_direct['top_1_total']}")
    print(
        "Raw query direct-answer hits: "
        f"Top 1 {raw_direct['top_1_hits']}/{raw_direct['top_1_total']}, "
        f"Top 3 {raw_direct['top_3_hits']}/{raw_direct['top_3_total']}"
    )
    print(
        "Raw query source hits: "
        f"Top 1 {raw_source['top_1_hits']}/{raw_source['top_1_total']}, "
        f"Top 3 {raw_source['top_3_hits']}/{raw_source['top_3_total']}"
    )
    print(
        "Runtime rule query direct-answer hits: "
        f"Top 1 {runtime_direct['top_1_hits']}/{runtime_direct['top_1_total']}, "
        f"Top 3 {runtime_direct['top_3_hits']}/{runtime_direct['top_3_total']}"
    )
    print(
        "Runtime rule query source hits: "
        f"Top 1 {runtime_source['top_1_hits']}/{runtime_source['top_1_total']}, "
        f"Top 3 {runtime_source['top_3_hits']}/{runtime_source['top_3_total']}"
    )
    print(
        "Runtime fused query direct-answer hits: "
        f"Top 1 {fused_direct['top_1_hits']}/{fused_direct['top_1_total']}, "
        f"Top 3 {fused_direct['top_3_hits']}/{fused_direct['top_3_total']}"
    )
    print(
        "Runtime fused query source hits: "
        f"Top 1 {fused_source['top_1_hits']}/{fused_source['top_1_total']}, "
        f"Top 3 {fused_source['top_3_hits']}/{fused_source['top_3_total']}"
    )
    print(f"Dataset SHA-256: {report['dataset']['sha256']}")
    print(f"Knowledge SHA-256: {report['knowledge_snapshot']['sha256']}")
    print(f"Label contract: {report['label_contract_version']}")
    print("BGE status: historical_not_rerun")


if __name__ == "__main__":
    main()
