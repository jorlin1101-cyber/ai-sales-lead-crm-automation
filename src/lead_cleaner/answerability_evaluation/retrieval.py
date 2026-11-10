"""Offline execution of the three existing production retrieval paths.

Only messages and production knowledge fields enter retrieval. Evaluation labels,
validity annotations and relevance judgments remain outside the system under test.
"""

from __future__ import annotations

from typing import Any

from lead_cleaner.evaluation._quality_runtime import NetworkGuard
from lead_cleaner.rag.bm25_retriever import build_bm25_index
from lead_cleaner.rag.demo_embedding_provider import KeywordEmbeddingProvider
from lead_cleaner.rag.dense_retriever import build_dense_index
from lead_cleaner.rag.hybrid_retriever import retrieve_hybrid
from lead_cleaner.rag.query_builder import build_lead_features_query
from lead_cleaner.rag.query_fusion import fuse_query_result_lists
from lead_cleaner.rag.retrieval_intent import build_retrieval_queries
from lead_cleaner.rag.schemas import KnowledgeChunk
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.services.rule_feature_extractor import RuleFeatureExtractor

PATHS = ("raw_query", "runtime_rule_query", "runtime_fused_query")
TOP_K = 3
CANDIDATE_TOP_K = 5
RRF_K = 60


def run_retrieval(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    """Run every single-turn case through all three real keyword/RRF paths."""
    rows: list[dict[str, Any]] = []
    interrupted = False
    with NetworkGuard() as guard:
        for case in dataset["cases"]:
            if len(case["turns"]) != 1:
                continue
            turn = case["turns"][0]
            for path in PATHS:
                row: dict[str, Any] = {
                    "protocol_id": dataset.get("protocol_id", "p0-02.v1"),
                    "case_id": case["case_id"],
                    "turn_id": turn["turn_id"],
                    "path": path,
                    "query": turn["message"],
                    "retrieval_queries": [],
                    "results": [],
                    "execution_status": "not_run" if interrupted else "completed",
                    "error_type": "interrupted" if interrupted else None,
                    "top_k": TOP_K,
                    "candidate_top_k": CANDIDATE_TOP_K,
                    "rrf_k": RRF_K,
                }
                rows.append(row)
                if interrupted:
                    continue
                try:
                    # Build from actual text, never from support_groups or gold ranks.
                    snapshot = dataset["snapshots"][case["snapshot_id"]]
                    chunks = [KnowledgeChunk.model_validate(c["chunk"]) for c in snapshot["chunks"]]
                    provider = KeywordEmbeddingProvider()
                    bm25 = build_bm25_index(chunks)
                    dense = build_dense_index(chunks, provider)
                    queries = [turn["message"]]
                    if path != "raw_query":
                        lead = CleanedLead(
                            lead_id=f"answerability-{case['case_id']}",
                            name="Evaluation Lead",
                            email="eval@example.com",
                            company_name="",
                            message=turn["message"],
                            source="answerability-eval",
                        )
                        features = RuleFeatureExtractor().extract(lead).features
                        queries = (
                            [build_lead_features_query(features)]
                            if path == "runtime_rule_query"
                            else build_retrieval_queries(lead, features)
                        )
                    row["retrieval_queries"] = queries
                    result_lists = [
                        retrieve_hybrid(
                            query=query,
                            bm25_index=bm25,
                            dense_index=dense,
                            embedding_provider=provider,
                            top_k=TOP_K,
                            candidate_top_k=CANDIDATE_TOP_K,
                            rrf_k=RRF_K,
                        )
                        for query in queries
                    ]
                    results = (
                        result_lists[0]
                        if len(result_lists) == 1
                        else fuse_query_result_lists(result_lists, top_k=TOP_K, rrf_k=RRF_K)
                    )
                    row["results"] = [result.model_dump(mode="json") for result in results]
                except KeyboardInterrupt:
                    interrupted = True
                    row.update(execution_status="error", error_type="interrupted")
                except Exception as error:
                    row.update(execution_status="error", error_type=type(error).__name__)
                row["network_guard"] = guard.summary()
    return rows
