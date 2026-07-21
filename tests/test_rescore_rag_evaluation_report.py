import json
from datetime import UTC, datetime
from pathlib import Path

from lead_cleaner.rag.evaluation_report import sha256_file
from scripts.merge_rag_judgment_review import merge_reviewed_judgments
from scripts.rescore_rag_evaluation_report import rescore_report_from_stored_rankings
from tests.test_merge_rag_judgment_review import (
    _chunks_payload,
    _eval_payload,
    _review_payload,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _stored_case() -> dict[str, object]:
    return {
        "query_id": "payment_001",
        "input_query": "When is payment due?",
        "retrieval_queries": ["When is payment due?"],
        "query_changed": False,
        "direct_top_1_hit": True,
        "direct_top_3_hit": True,
        "source_top_1_hit": True,
        "source_top_3_hit": True,
        "reciprocal_rank_at_3": 1.0,
        "ndcg_at_3": 1.0,
        "facet_recall_at_3": 1.0,
        "unjudged_rate_at_3": 0.5,
        "query_latency_ms": 1.0,
        "retrieved_sources": [
            {
                "chunk_id": "chunk_direct",
                "source_title": "Payment FAQ",
                "section": "Payment Schedule",
                "rank": 1,
                "judged": True,
            },
            {
                "chunk_id": "chunk_supporting",
                "source_title": "Payment FAQ",
                "section": "Sales Notes",
                "rank": 2,
                "judged": False,
            },
            {
                "chunk_id": "chunk_other",
                "source_title": "Travel FAQ",
                "section": "Permit Notes",
                "rank": 3,
                "judged": False,
            },
        ],
    }


def test_rescore_report_uses_stored_rankings_without_network(tmp_path: Path) -> None:
    old_eval_path = tmp_path / "old-eval.json"
    merged_eval_path = tmp_path / "merged-eval.json"
    chunks_path = tmp_path / "chunks.json"
    review_path = tmp_path / "review.json"
    source_report_path = tmp_path / "source-report.json"
    output_path = tmp_path / "rescored-report.json"
    _write_json(old_eval_path, _eval_payload())
    chunks = _chunks_payload()
    chunks.append(
        {
            **chunks[0],
            "chunk_id": "chunk_other",
            "notion_page_id": "page_002",
            "source_title": "Travel FAQ",
            "source_path": "FAQ / Travel FAQ",
            "section": "Permit Notes",
            "chunk_index": 0,
            "text": "Permit applications should be submitted early.",
        }
    )
    _write_json(chunks_path, chunks)
    review = _review_payload(eval_path=old_eval_path, chunks_path=chunks_path)
    _write_json(review_path, review)
    merge_reviewed_judgments(
        review_path=review_path,
        eval_path=old_eval_path,
        chunks_path=chunks_path,
        output_path=merged_eval_path,
    )

    stored_evaluation = {
        "path_name": "raw_query",
        "description": "Stored test ranking.",
        "metrics": {},
        "latency": {"query_count": 1},
        "cases": [_stored_case()],
    }
    source_report = {
        "report_schema_version": "rag-eval-v4",
        "label_contract_version": "paired-graded-relevance-v2",
        "retrieval_pipeline_version": "bge-m3-rrf-v1",
        "generated_at_utc": "2026-07-21T00:00:00+00:00",
        "backend": "bge_rrf",
        "network_access_required": True,
        "dataset": {"sha256": sha256_file(old_eval_path)},
        "knowledge_snapshot": {"sha256": sha256_file(chunks_path)},
        "evaluations": {
            "raw_query": stored_evaluation,
            "runtime_rule_query": {
                **stored_evaluation,
                "path_name": "runtime_rule_query",
            },
            "runtime_fused_query": {
                **stored_evaluation,
                "path_name": "runtime_fused_query",
            },
        },
        "comparison": {"metric": "grade_3_direct_answer_hit"},
        "bge_evaluation": {"status": "completed"},
        "limitations": [],
    }
    _write_json(source_report_path, source_report)

    report = rescore_report_from_stored_rankings(
        source_report_path=source_report_path,
        review_path=review_path,
        eval_path=merged_eval_path,
        chunks_path=chunks_path,
        output_path=output_path,
        rescored_at=datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )

    assert report["dataset"]["judgment_count"] == 2
    ranking = report["evaluations"]["runtime_fused_query"]["metrics"]["ranking"]
    assert ranking["mean_unjudged_rate_at_3"] == 0.3333
    rescoring = report["rescoring"]
    assert rescoring["status"] == "completed_from_stored_rankings"
    assert rescoring["rescored_at_utc"] == "2026-07-21T12:00:00+00:00"
    assert rescoring["source_dataset_sha256"] == sha256_file(old_eval_path)
    assert rescoring["reviewed_judgment_count"] == 1
    assert rescoring["retrieval_rerun"] is False
    assert rescoring["network_access_required"] is False
    sources = report["evaluations"]["runtime_fused_query"]["cases"][0]["retrieved_sources"]
    assert sources[1]["judged"] is True
    assert sources[1]["relevance_grade"] == 1
    assert json.loads(output_path.read_text(encoding="utf-8")) == report
