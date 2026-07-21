import argparse
import json
from pathlib import Path
from typing import Any

from lead_cleaner.rag.evaluation_report import load_eval_cases, sha256_file
from lead_cleaner.rag.knowledge_loader import load_knowledge_chunks


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "rag-eval-bge-m3-v4-20260721.json"
DEFAULT_EVAL_PATH = PROJECT_ROOT / "data" / "rag_eval" / "eval_queries.json"
DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "data" / "knowledge_snapshot" / "knowledge_chunks.json"
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "rag_eval" / "review" / "bge-m3-v4-unjudged-review.json"
)
DEFAULT_EVALUATION_PATH = "runtime_fused_query"


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


def export_unjudged_pool(
    *,
    report_path: str | Path,
    eval_path: str | Path,
    chunks_path: str | Path,
    output_path: str | Path,
    evaluation_path: str = DEFAULT_EVALUATION_PATH,
) -> dict[str, Any]:
    report_path = Path(report_path)
    eval_path = Path(eval_path)
    chunks_path = Path(chunks_path)
    output_path = Path(output_path)

    report = _load_json_object(report_path)
    if report.get("report_schema_version") != "rag-eval-v4":
        raise ValueError("The source report must use report_schema_version rag-eval-v4.")
    if report.get("dataset", {}).get("sha256") != sha256_file(eval_path):
        raise ValueError("The evaluation dataset does not match the source report hash.")
    if report.get("knowledge_snapshot", {}).get("sha256") != sha256_file(chunks_path):
        raise ValueError("The knowledge snapshot does not match the source report hash.")

    evaluations = report.get("evaluations")
    if not isinstance(evaluations, dict) or evaluation_path not in evaluations:
        raise ValueError(f"Evaluation path {evaluation_path!r} is missing from the report.")
    selected_evaluation = evaluations[evaluation_path]
    if not isinstance(selected_evaluation, dict):
        raise ValueError(f"Evaluation path {evaluation_path!r} must be an object.")
    report_cases = selected_evaluation.get("cases")
    if not isinstance(report_cases, list):
        raise ValueError(f"Evaluation path {evaluation_path!r} must contain a cases list.")

    eval_cases = load_eval_cases(eval_path)
    eval_cases_by_id = {case.query_id: case for case in eval_cases}
    chunks = load_knowledge_chunks(chunks_path)
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    review_items: list[dict[str, Any]] = []

    for report_case in report_cases:
        if not isinstance(report_case, dict):
            raise ValueError("Each report case must be an object.")
        query_id = report_case.get("query_id")
        if not isinstance(query_id, str) or query_id not in eval_cases_by_id:
            raise ValueError(f"Unknown query_id in report: {query_id!r}.")
        eval_case = eval_cases_by_id[query_id]
        retrieved_sources = report_case.get("retrieved_sources")
        if not isinstance(retrieved_sources, list):
            raise ValueError(f"Report case {query_id!r} must contain retrieved_sources.")

        for source in retrieved_sources:
            if not isinstance(source, dict) or source.get("judged") is not False:
                continue
            chunk_id = source.get("chunk_id")
            if not isinstance(chunk_id, str) or chunk_id not in chunks_by_id:
                raise ValueError(f"Unknown chunk_id in report: {chunk_id!r}.")
            chunk = chunks_by_id[chunk_id]
            if (
                source.get("source_title") != chunk.source_title
                or source.get("section") != chunk.section
            ):
                raise ValueError(f"Report metadata does not match knowledge chunk {chunk_id}.")

            review_items.append(
                {
                    "review_id": f"{query_id}::{chunk_id}",
                    "query_id": query_id,
                    "query": eval_case.query,
                    "language": eval_case.language,
                    "query_type": eval_case.query_type,
                    "facets": [facet.model_dump(mode="json") for facet in eval_case.facets],
                    "retrieval_queries": report_case.get("retrieval_queries", []),
                    "rank": source.get("rank"),
                    "chunk_id": chunk.chunk_id,
                    "source_title": chunk.source_title,
                    "section": chunk.section,
                    "chunk_text": chunk.text,
                    "current_status": "unjudged",
                    "review": {
                        "relevance_grade": None,
                        "covers_facets": [],
                        "reason": "",
                    },
                }
            )

    review_payload = {
        "review_schema_version": "rag-unjudged-review-v1",
        "source_report": _portable_path(report_path),
        "evaluation_path": evaluation_path,
        "label_contract_version": report.get("label_contract_version"),
        "dataset_sha256": report["dataset"]["sha256"],
        "knowledge_sha256": report["knowledge_snapshot"]["sha256"],
        "grading_guide": {
            "3": "Directly answers at least one declared facet.",
            "2": "Provides clearly useful supporting information.",
            "1": "Is topically related but offers little practical help.",
            "0": "Has been reviewed and is irrelevant to the query facets.",
        },
        "review_instructions": [
            "Fill review.relevance_grade with 0, 1, 2, or 3.",
            "Use an empty covers_facets list for grade 0.",
            "For grades 1, 2, or 3, select one or more facet_id values listed on the item.",
            "Write a short evidence-based reason for every judgment.",
        ],
        "item_count": len(review_items),
        "items": review_items,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(review_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return review_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export unjudged Top-K RAG results into a manual review file.",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--eval", type=Path, default=DEFAULT_EVAL_PATH)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--evaluation-path", default=DEFAULT_EVALUATION_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    review_payload = export_unjudged_pool(
        report_path=args.report,
        eval_path=args.eval,
        chunks_path=args.chunks,
        output_path=args.output,
        evaluation_path=args.evaluation_path,
    )
    print(f"Review file: {args.output}")
    print(f"Evaluation path: {review_payload['evaluation_path']}")
    print(f"Unjudged review items: {review_payload['item_count']}")


if __name__ == "__main__":
    main()
