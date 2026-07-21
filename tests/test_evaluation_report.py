import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lead_cleaner.rag.evaluation_report import (
    run_bge_evaluation,
    run_keyword_evaluation,
    sha256_file,
    write_evaluation_report,
)
from lead_cleaner.rag.demo_embedding_provider import KeywordEmbeddingProvider


CHUNKS_PATH = Path("data/knowledge_snapshot/knowledge_chunks.json")
EVAL_PATH = Path("data/rag_eval/eval_queries.json")


def test_keyword_evaluation_report_uses_the_graded_label_contract() -> None:
    report = run_keyword_evaluation(
        chunks_path=CHUNKS_PATH,
        eval_queries_path=EVAL_PATH,
        generated_at=datetime(2026, 7, 21, tzinfo=UTC),
    )

    assert report["report_schema_version"] == "rag-eval-v4"
    assert report["label_contract_version"] == "paired-graded-relevance-v2"
    assert report["retrieval_pipeline_version"] == "keyword-rrf-v1"
    assert report["network_access_required"] is False
    assert report["dataset"] == {
        "path": "data/rag_eval/eval_queries.json",
        "sha256": sha256_file(EVAL_PATH),
        "eval_case_count": 18,
        "facet_count": 25,
        "judgment_count": 103,
    }
    assert report["knowledge_snapshot"]["knowledge_chunk_count"] == 47
    assert report["knowledge_snapshot"]["path"] == ("data/knowledge_snapshot/knowledge_chunks.json")
    assert report["knowledge_snapshot"]["sha256"] == sha256_file(CHUNKS_PATH)

    raw_evaluation = report["evaluations"]["raw_query"]
    runtime_evaluation = report["evaluations"]["runtime_rule_query"]
    fused_evaluation = report["evaluations"]["runtime_fused_query"]

    assert raw_evaluation["metrics"]["direct"]["top_1_hits"] == 13
    assert raw_evaluation["metrics"]["direct"]["top_3_hits"] == 17
    assert raw_evaluation["metrics"]["source"]["top_1_hits"] == 17
    assert raw_evaluation["metrics"]["source"]["top_3_hits"] == 18
    assert raw_evaluation["metrics"]["ranking"] == {
        "mean_reciprocal_rank_at_3": 0.8148,
        "mean_ndcg_at_3": 0.6368,
        "mean_facet_recall_at_3": 0.8889,
        "mean_unjudged_rate_at_3": 0.2778,
    }
    assert runtime_evaluation["metrics"]["direct"]["top_1_hits"] == 7
    assert runtime_evaluation["metrics"]["direct"]["top_3_hits"] == 12
    assert fused_evaluation["metrics"]["direct"]["top_1_hits"] == 11
    assert fused_evaluation["metrics"]["direct"]["top_3_hits"] == 17
    assert fused_evaluation["metrics"]["source"]["top_1_hits"] == 17
    assert fused_evaluation["metrics"]["source"]["top_3_hits"] == 18
    assert report["comparison"]["metric"] == "grade_3_direct_answer_hit"
    assert report["comparison"]["fused_minus_raw_top_3_hits"] == 0

    assert report["retrieval"]["query_fusion"] == "weighted_rrf"
    assert report["retrieval"]["primary_query_weight"] == 2
    assert report["bge_evaluation"]["status"] == "historical_not_rerun"
    assert report["indexing"]["timer"] == "time.perf_counter"
    assert raw_evaluation["latency"]["query_count"] == 18
    assert runtime_evaluation["latency"]["query_count"] == 18
    assert fused_evaluation["latency"]["query_count"] == 18
    assert "excludes file loading" in raw_evaluation["latency"]["query_latency_scope"]

    raw_cases = {case["query_id"]: case for case in raw_evaluation["cases"]}
    runtime_cases = {case["query_id"]: case for case in runtime_evaluation["cases"]}
    fused_cases = {case["query_id"]: case for case in fused_evaluation["cases"]}
    permit_query = "Do foreign travelers need a permit to visit Tibet?"
    assert raw_cases["tibet_permit_001"]["retrieval_queries"] == [permit_query]
    assert raw_cases["tibet_permit_001"]["direct_top_1_hit"] is True
    assert runtime_cases["tibet_permit_001"]["retrieval_queries"] == [
        "individual traveler | destinations Tibet"
    ]
    assert runtime_cases["tibet_permit_001"]["direct_top_1_hit"] is False
    assert runtime_cases["tibet_permit_001"]["direct_top_3_hit"] is True
    assert fused_cases["tibet_permit_001"]["retrieval_queries"] == [
        permit_query,
        (
            "individual traveler | destinations Tibet | "
            "travel permit entry requirements foreign travelers"
        ),
    ]
    assert fused_cases["tibet_permit_001"]["direct_top_1_hit"] is True

    source_fields = {
        key
        for evaluation in report["evaluations"].values()
        for case in evaluation["cases"]
        for source in case["retrieved_sources"]
        for key in source
    }
    assert source_fields == {
        "chunk_id",
        "source_title",
        "section",
        "rank",
        "relevance_grade",
        "judged",
        "relevant_match",
        "direct_match",
        "source_match",
        "covers_facets",
    }


def test_keyword_evaluation_requires_a_top_3_window() -> None:
    with pytest.raises(ValueError, match="at least 3"):
        run_keyword_evaluation(
            chunks_path=CHUNKS_PATH,
            eval_queries_path=EVAL_PATH,
            top_k=2,
        )


def test_bge_report_uses_the_same_v4_metrics_with_an_injected_provider() -> None:
    report = run_bge_evaluation(
        chunks_path=CHUNKS_PATH,
        eval_queries_path=EVAL_PATH,
        embedding_provider=KeywordEmbeddingProvider(),
        generated_at=datetime(2026, 7, 21, tzinfo=UTC),
    )

    assert report["report_schema_version"] == "rag-eval-v4"
    assert report["label_contract_version"] == "paired-graded-relevance-v2"
    assert report["retrieval_pipeline_version"] == "bge-m3-rrf-v1"
    assert report["backend"] == "bge_rrf"
    assert report["network_access_required"] is True
    assert report["bge_evaluation"]["status"] == "completed"
    assert report["bge_evaluation"]["current_metrics"] == "evaluations"
    assert report["indexing"]["query_embeddings_prewarmed"] is True
    assert report["indexing"]["unique_query_embedding_count"] > 18
    assert (
        "excludes external embedding API time"
        in report["evaluations"]["raw_query"]["latency"]["query_latency_scope"]
    )
    assert report["evaluations"]["raw_query"]["metrics"]["direct"]["top_3_hits"] == 17


def test_write_evaluation_report_uses_utf8_json(tmp_path: Path) -> None:
    report = run_keyword_evaluation(
        chunks_path=CHUNKS_PATH,
        eval_queries_path=EVAL_PATH,
        generated_at=datetime(2026, 7, 21, tzinfo=UTC),
    )
    output_path = tmp_path / "report.json"

    write_evaluation_report(report, output_path)

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["evaluations"] == report["evaluations"]
    assert saved["dataset"]["sha256"] == report["dataset"]["sha256"]
