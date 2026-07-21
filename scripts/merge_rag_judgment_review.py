import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from lead_cleaner.rag.eval_runner import validate_eval_cases_against_chunks
from lead_cleaner.rag.eval_schemas import RagEvalCase, RelevanceJudgment
from lead_cleaner.rag.evaluation_report import load_eval_cases, sha256_file
from lead_cleaner.rag.knowledge_loader import load_knowledge_chunks


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW_PATH = (
    PROJECT_ROOT / "data" / "rag_eval" / "review" / "bge-m3-v4-unjudged-review.json"
)
DEFAULT_EVAL_PATH = PROJECT_ROOT / "data" / "rag_eval" / "eval_queries.json"
DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "data" / "knowledge_snapshot" / "knowledge_chunks.json"
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "rag_eval" / "review" / "eval_queries-merged-candidate.json"
)

REVIEW_SCHEMA_VERSION = "rag-unjudged-review-v1"
LABEL_CONTRACT_VERSION = "paired-graded-relevance-v2"
_eval_case_list_adapter = TypeAdapter(list[RagEvalCase])


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return payload


def _review_items(review_payload: dict[str, Any]) -> list[dict[str, Any]]:
    if review_payload.get("review_schema_version") != REVIEW_SCHEMA_VERSION:
        raise ValueError(f"Review file must use review_schema_version {REVIEW_SCHEMA_VERSION}.")
    if review_payload.get("label_contract_version") != LABEL_CONTRACT_VERSION:
        raise ValueError(f"Review file must use label_contract_version {LABEL_CONTRACT_VERSION}.")
    items = review_payload.get("items")
    if not isinstance(items, list):
        raise ValueError("Review file must contain an items list.")
    if review_payload.get("item_count") != len(items):
        raise ValueError("Review item_count does not match the items list length.")
    if not items:
        raise ValueError("Review file does not contain any items.")
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("Every review item must be a JSON object.")
    return items


def _assert_source_hashes(
    *,
    review_payload: dict[str, Any],
    eval_path: Path,
    chunks_path: Path,
) -> None:
    if review_payload.get("dataset_sha256") != sha256_file(eval_path):
        raise ValueError("The evaluation dataset changed after the review pool was exported.")
    if review_payload.get("knowledge_sha256") != sha256_file(chunks_path):
        raise ValueError("The knowledge snapshot changed after the review pool was exported.")


def _make_judgment(item: dict[str, Any]) -> RelevanceJudgment:
    review = item.get("review")
    if not isinstance(review, dict):
        raise ValueError(f"Review item {item.get('review_id')!r} has no review object.")
    return RelevanceJudgment.model_validate(
        {
            "source_title": item.get("source_title"),
            "section": item.get("section"),
            "relevance_grade": review.get("relevance_grade"),
            "covers_facets": review.get("covers_facets"),
            "reason": review.get("reason"),
        }
    )


def merge_reviewed_judgments(
    *,
    review_path: str | Path,
    eval_path: str | Path,
    chunks_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    review_path = Path(review_path)
    eval_path = Path(eval_path)
    chunks_path = Path(chunks_path)
    output_path = Path(output_path)

    review_payload = _load_json_object(review_path)
    items = _review_items(review_payload)
    _assert_source_hashes(
        review_payload=review_payload,
        eval_path=eval_path,
        chunks_path=chunks_path,
    )

    eval_cases = load_eval_cases(eval_path)
    chunks = load_knowledge_chunks(chunks_path)
    cases_by_id = {case.query_id: case.model_copy(deep=True) for case in eval_cases}
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}

    review_ids: set[str] = set()
    reviewed_keys: set[tuple[str, str, str]] = set()
    grades: Counter[int] = Counter()
    before_count = sum(len(case.judgments) for case in eval_cases)

    for item in items:
        review_id = item.get("review_id")
        if not isinstance(review_id, str) or not review_id:
            raise ValueError("Every review item must have a non-empty review_id.")
        if review_id in review_ids:
            raise ValueError(f"Duplicate review_id: {review_id}.")
        review_ids.add(review_id)

        if item.get("current_status") != "reviewed":
            raise ValueError(f"Review item {review_id!r} is not marked reviewed.")
        query_id = item.get("query_id")
        if not isinstance(query_id, str) or query_id not in cases_by_id:
            raise ValueError(f"Review item {review_id!r} has an unknown query_id.")
        eval_case = cases_by_id[query_id]
        if item.get("query") != eval_case.query:
            raise ValueError(f"Review item {review_id!r} query text does not match.")

        declared_facets = {facet.facet_id for facet in eval_case.facets}
        item_facets = item.get("facets")
        if not isinstance(item_facets, list):
            raise ValueError(f"Review item {review_id!r} has no facets list.")
        item_facet_ids = {
            facet.get("facet_id")
            for facet in item_facets
            if isinstance(facet, dict) and isinstance(facet.get("facet_id"), str)
        }
        if item_facet_ids != declared_facets:
            raise ValueError(f"Review item {review_id!r} facet contract does not match.")

        chunk_id = item.get("chunk_id")
        if not isinstance(chunk_id, str) or chunk_id not in chunks_by_id:
            raise ValueError(f"Review item {review_id!r} has an unknown chunk_id.")
        chunk = chunks_by_id[chunk_id]
        if (
            item.get("source_title") != chunk.source_title
            or item.get("section") != chunk.section
            or item.get("chunk_text") != chunk.text
        ):
            raise ValueError(f"Review item {review_id!r} does not match its knowledge chunk.")

        judgment = _make_judgment(item)
        key = (query_id, judgment.source_title, judgment.section)
        if key in reviewed_keys:
            raise ValueError(f"Duplicate reviewed judgment: {key!r}.")
        reviewed_keys.add(key)
        existing_keys = {
            (query_id, existing.source_title, existing.section) for existing in eval_case.judgments
        }
        if key in existing_keys:
            raise ValueError(f"Judgment already exists in the evaluation dataset: {key!r}.")

        eval_case.judgments.append(judgment)
        grades[judgment.relevance_grade] += 1

    merged_cases = _eval_case_list_adapter.validate_python(
        [case.model_dump(mode="json") for case in cases_by_id.values()]
    )
    validate_eval_cases_against_chunks(merged_cases, chunks)
    after_count = sum(len(case.judgments) for case in merged_cases)
    if after_count != before_count + len(items):
        raise ValueError("The merged judgment count is inconsistent.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            [case.model_dump(mode="json") for case in merged_cases],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "eval_case_count": len(merged_cases),
        "judgment_count_before": before_count,
        "reviewed_judgment_count": len(items),
        "judgment_count_after": after_count,
        "grade_counts": {str(grade): grades[grade] for grade in range(4)},
        "source_dataset_sha256": review_payload["dataset_sha256"],
        "merged_dataset_sha256": sha256_file(output_path),
        "knowledge_sha256": review_payload["knowledge_sha256"],
        "output_path": output_path.as_posix(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely merge reviewed RAG judgments into a candidate dataset.",
    )
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW_PATH)
    parser.add_argument("--eval", type=Path, default=DEFAULT_EVAL_PATH)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = merge_reviewed_judgments(
        review_path=args.review,
        eval_path=args.eval,
        chunks_path=args.chunks,
        output_path=args.output,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
