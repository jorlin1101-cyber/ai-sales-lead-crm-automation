import hashlib
import json
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import TypeAdapter

from lead_cleaner.rag.bge_embedding_provider import (
    DEFAULT_BGE_API_BASE_URL,
    DEFAULT_BGE_EMBEDDING_MODEL,
    BgeM3EmbeddingProvider,
)
from lead_cleaner.rag.bm25_retriever import BM25Index, build_bm25_index
from lead_cleaner.rag.demo_embedding_provider import KeywordEmbeddingProvider
from lead_cleaner.rag.dense_retriever import (
    DenseIndex,
    EmbeddingProvider,
    build_dense_index,
)
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
from lead_cleaner.rag.eval_schemas import RagEvalCase
from lead_cleaner.rag.hybrid_retriever import retrieve_hybrid
from lead_cleaner.rag.knowledge_loader import load_knowledge_chunks
from lead_cleaner.rag.query_builder import build_lead_features_query
from lead_cleaner.rag.query_fusion import (
    DEFAULT_PRIMARY_QUERY_WEIGHT,
    fuse_query_result_lists,
)
from lead_cleaner.rag.retrieval_intent import build_retrieval_queries
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.services.rule_feature_extractor import RuleFeatureExtractor


REPORT_SCHEMA_VERSION = "rag-eval-v4"
LABEL_CONTRACT_VERSION = "paired-graded-relevance-v2"
RETRIEVAL_PIPELINE_VERSION = "keyword-rrf-v1"
BGE_RETRIEVAL_PIPELINE_VERSION = "bge-m3-rrf-v1"
_eval_case_list_adapter = TypeAdapter(list[RagEvalCase])


class _CachingEmbeddingProvider:
    """Cache evaluation vectors so prewarmed queries never call the API again."""

    def __init__(self, provider: EmbeddingProvider) -> None:
        self.model_name = provider.model_name
        self._provider = provider
        self._vectors_by_text: dict[str, list[float]] = {}

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        missing_texts = list(
            dict.fromkeys(text for text in texts if text not in self._vectors_by_text)
        )
        if missing_texts:
            missing_vectors = self._provider.embed_texts(missing_texts)
            if len(missing_vectors) != len(missing_texts):
                raise ValueError("Embedding provider returned an unexpected vector count.")
            self._vectors_by_text.update(zip(missing_texts, missing_vectors))
        return [self._vectors_by_text[text] for text in texts]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _portable_path(path: Path) -> str:
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def load_eval_cases(path: str | Path) -> list[RagEvalCase]:
    eval_text = Path(path).read_text(encoding="utf-8")
    cases = _eval_case_list_adapter.validate_json(eval_text)
    if not cases:
        raise ValueError("RAG evaluation dataset cannot be empty.")
    return cases


def _nearest_rank_p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _metric_summary(*, top_1_hits: int, top_3_hits: int, total: int) -> dict[str, Any]:
    return {
        "top_1_hits": top_1_hits,
        "top_1_total": total,
        "top_1_hit_rate_percent": round(top_1_hits / total * 100, 2),
        "top_3_hits": top_3_hits,
        "top_3_total": total,
        "top_3_hit_rate_percent": round(top_3_hits / total * 100, 2),
    }


def _latency_summary(
    values: list[float],
    *,
    path_name: str,
    query_embeddings_prewarmed: bool,
) -> dict[str, Any]:
    path_scope = {
        "raw_query": "one direct retrieval call",
        "runtime_rule_query": (
            "deterministic rule feature extraction, feature-only query building, and one "
            "retrieval call"
        ),
        "runtime_fused_query": (
            "contact-data sanitization, deterministic rule feature extraction, "
            "RetrievalIntent construction, two retrieval calls, and query-level RRF"
        ),
    }[path_name]
    prewarm_note = (
        " Query embeddings were prewarmed in one batch, so this per-query latency "
        "excludes external embedding API time."
        if query_embeddings_prewarmed
        else ""
    )
    return {
        "timer": "time.perf_counter",
        "query_latency_scope": (
            f"Each case is measured after both indexes are built; it includes {path_scope}. "
            "Each retrieval call includes BM25, keyword-vector dense retrieval, and RRF. "
            "It excludes file loading, index building, application startup, feature model "
            f"loading, and JSON report serialization.{prewarm_note}"
        ),
        "query_count": len(values),
        "mean_query_ms": round(mean(values), 3),
        "p95_query_ms": round(_nearest_rank_p95(values), 3),
        "max_query_ms": round(max(values), 3),
    }


def _raw_queries(eval_case: RagEvalCase) -> list[str]:
    return [eval_case.query]


def _make_eval_lead(eval_case: RagEvalCase) -> CleanedLead:
    return CleanedLead(
        lead_id=f"rag-eval-{eval_case.query_id}",
        name="Evaluation Lead",
        email="eval@example.com",
        company_name="",
        message=eval_case.query,
        source="rag-eval",
    )


def _make_runtime_rule_query_builder() -> Callable[[RagEvalCase], list[str]]:
    extractor = RuleFeatureExtractor()

    def build_query(eval_case: RagEvalCase) -> list[str]:
        cleaned_lead = _make_eval_lead(eval_case)
        outcome = extractor.extract(cleaned_lead)
        return [build_lead_features_query(outcome.features)]

    return build_query


def _make_runtime_fused_query_builder() -> Callable[[RagEvalCase], list[str]]:
    extractor = RuleFeatureExtractor()

    def build_queries(eval_case: RagEvalCase) -> list[str]:
        cleaned_lead = _make_eval_lead(eval_case)
        outcome = extractor.extract(cleaned_lead)
        return build_retrieval_queries(cleaned_lead, outcome.features)

    return build_queries


def _evaluate_query_path(
    *,
    path_name: str,
    description: str,
    eval_cases: list[RagEvalCase],
    bm25_index: BM25Index,
    dense_index: DenseIndex,
    provider: EmbeddingProvider,
    query_builder: Callable[[RagEvalCase], list[str]],
    top_k: int,
    candidate_top_k: int,
    rrf_k: int,
    timer: Callable[[], float],
    query_embeddings_prewarmed: bool,
) -> dict[str, Any]:
    direct_top_1_hits = 0
    direct_top_3_hits = 0
    source_top_1_hits = 0
    source_top_3_hits = 0
    reciprocal_ranks: list[float] = []
    ndcg_values: list[float] = []
    facet_recall_values: list[float] = []
    unjudged_rate_values: list[float] = []
    query_latencies_ms: list[float] = []
    case_results: list[dict[str, Any]] = []

    for eval_case in eval_cases:
        query_started = timer()
        retrieval_queries = query_builder(eval_case)
        result_lists = [
            retrieve_hybrid(
                query=retrieval_query,
                bm25_index=bm25_index,
                dense_index=dense_index,
                embedding_provider=provider,
                top_k=top_k,
                candidate_top_k=candidate_top_k,
                rrf_k=rrf_k,
            )
            for retrieval_query in retrieval_queries
        ]
        results = (
            result_lists[0]
            if len(result_lists) == 1
            else fuse_query_result_lists(result_lists, top_k=top_k, rrf_k=rrf_k)
        )
        latency_ms = (timer() - query_started) * 1000
        query_latencies_ms.append(latency_ms)

        direct_top_1_hit = has_expected_match(results, eval_case, top_k=1)
        direct_top_3_hit = has_expected_match(results, eval_case, top_k=3)
        source_top_1_hit = has_expected_source(results, eval_case, top_k=1)
        source_top_3_hit = has_expected_source(results, eval_case, top_k=3)
        case_reciprocal_rank = reciprocal_rank(results, eval_case)
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

        case_results.append(
            {
                "query_id": eval_case.query_id,
                "input_query": eval_case.query,
                "retrieval_queries": retrieval_queries,
                "query_changed": retrieval_queries != [eval_case.query],
                "direct_top_1_hit": direct_top_1_hit,
                "direct_top_3_hit": direct_top_3_hit,
                "source_top_1_hit": source_top_1_hit,
                "source_top_3_hit": source_top_3_hit,
                "reciprocal_rank_at_3": round(case_reciprocal_rank, 4),
                "ndcg_at_3": round(case_ndcg, 4),
                "facet_recall_at_3": round(case_facet_recall, 4),
                "unjudged_rate_at_3": round(case_unjudged_rate, 4),
                "query_latency_ms": round(latency_ms, 3),
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

    total = len(eval_cases)
    return {
        "path_name": path_name,
        "description": description,
        "metrics": {
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
        },
        "latency": _latency_summary(
            query_latencies_ms,
            path_name=path_name,
            query_embeddings_prewarmed=query_embeddings_prewarmed,
        ),
        "cases": case_results,
    }


def _run_evaluation(
    *,
    chunks_path: str | Path,
    eval_queries_path: str | Path,
    provider: EmbeddingProvider,
    backend: str,
    network_access_required: bool,
    retrieval_pipeline_version: str,
    pipeline_description: str,
    bge_evaluation: dict[str, Any],
    limitations: list[str],
    prewarm_query_embeddings: bool,
    top_k: int = 3,
    candidate_top_k: int = 5,
    rrf_k: int = 60,
    timer: Callable[[], float] = time.perf_counter,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate one embedding provider across the three frozen query paths."""

    if top_k < 3:
        raise ValueError("top_k must be at least 3 for the frozen Top-3 evaluation.")

    chunks_path = Path(chunks_path)
    eval_queries_path = Path(eval_queries_path)
    chunks = load_knowledge_chunks(chunks_path)
    eval_cases = load_eval_cases(eval_queries_path)
    validate_eval_cases_against_chunks(eval_cases, chunks)
    evaluation_provider: EmbeddingProvider = (
        _CachingEmbeddingProvider(provider) if prewarm_query_embeddings else provider
    )
    index_started = timer()
    bm25_index = build_bm25_index(chunks)
    dense_index = build_dense_index(
        chunks=chunks,
        embedding_provider=evaluation_provider,
    )
    index_build_ms = (timer() - index_started) * 1000

    rule_query_builder = _make_runtime_rule_query_builder()
    fused_query_builder = _make_runtime_fused_query_builder()
    query_embedding_prewarm_ms = 0.0
    unique_query_embedding_count = 0
    if prewarm_query_embeddings:
        unique_queries = list(
            dict.fromkeys(
                query
                for eval_case in eval_cases
                for query_builder in (
                    _raw_queries,
                    rule_query_builder,
                    fused_query_builder,
                )
                for query in query_builder(eval_case)
            )
        )
        prewarm_started = timer()
        evaluation_provider.embed_texts(unique_queries)
        query_embedding_prewarm_ms = (timer() - prewarm_started) * 1000
        unique_query_embedding_count = len(unique_queries)

    raw_evaluation = _evaluate_query_path(
        path_name="raw_query",
        description="The frozen evaluation question is sent directly to retrieval.",
        eval_cases=eval_cases,
        bm25_index=bm25_index,
        dense_index=dense_index,
        provider=evaluation_provider,
        query_builder=_raw_queries,
        top_k=top_k,
        candidate_top_k=candidate_top_k,
        rrf_k=rrf_k,
        timer=timer,
        query_embeddings_prewarmed=prewarm_query_embeddings,
    )
    runtime_rule_evaluation = _evaluate_query_path(
        path_name="runtime_rule_query",
        description=(
            "The frozen question is wrapped as a synthetic cleaned lead, passed through "
            "RuleFeatureExtractor and the production LeadFeatures query builder, then sent "
            "to retrieval."
        ),
        eval_cases=eval_cases,
        bm25_index=bm25_index,
        dense_index=dense_index,
        provider=evaluation_provider,
        query_builder=rule_query_builder,
        top_k=top_k,
        candidate_top_k=candidate_top_k,
        rrf_k=rrf_k,
        timer=timer,
        query_embeddings_prewarmed=prewarm_query_embeddings,
    )
    runtime_fused_evaluation = _evaluate_query_path(
        path_name="runtime_fused_query",
        description=(
            "The frozen question is sanitized, expanded with a deterministic "
            "RetrievalIntent, retrieved as two independent queries, and fused with RRF."
        ),
        eval_cases=eval_cases,
        bm25_index=bm25_index,
        dense_index=dense_index,
        provider=evaluation_provider,
        query_builder=fused_query_builder,
        top_k=top_k,
        candidate_top_k=candidate_top_k,
        rrf_k=rrf_k,
        timer=timer,
        query_embeddings_prewarmed=prewarm_query_embeddings,
    )

    raw_direct_metrics = raw_evaluation["metrics"]["direct"]
    runtime_direct_metrics = runtime_rule_evaluation["metrics"]["direct"]
    fused_direct_metrics = runtime_fused_evaluation["metrics"]["direct"]
    generated_time = generated_at or datetime.now(UTC)

    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "label_contract_version": LABEL_CONTRACT_VERSION,
        "retrieval_pipeline_version": retrieval_pipeline_version,
        "generated_at_utc": generated_time.astimezone(UTC).isoformat(),
        "backend": backend,
        "network_access_required": network_access_required,
        "dataset": {
            "path": _portable_path(eval_queries_path),
            "sha256": sha256_file(eval_queries_path),
            "eval_case_count": len(eval_cases),
            "facet_count": sum(len(case.facets) for case in eval_cases),
            "judgment_count": sum(len(case.judgments) for case in eval_cases),
        },
        "knowledge_snapshot": {
            "path": _portable_path(chunks_path),
            "sha256": sha256_file(chunks_path),
            "knowledge_chunk_count": len(chunks),
        },
        "retrieval": {
            "pipeline": pipeline_description,
            "embedding_provider": provider.model_name,
            "top_k": top_k,
            "candidate_top_k": candidate_top_k,
            "rrf_k": rrf_k,
            "query_fusion": "weighted_rrf",
            "primary_query_weight": DEFAULT_PRIMARY_QUERY_WEIGHT,
            "reranker_used": False,
        },
        "indexing": {
            "timer": "time.perf_counter",
            "index_build_ms": round(index_build_ms, 3),
            "query_embeddings_prewarmed": prewarm_query_embeddings,
            "unique_query_embedding_count": unique_query_embedding_count,
            "query_embedding_prewarm_ms": round(query_embedding_prewarm_ms, 3),
        },
        "evaluations": {
            "raw_query": raw_evaluation,
            "runtime_rule_query": runtime_rule_evaluation,
            "runtime_fused_query": runtime_fused_evaluation,
        },
        "comparison": {
            "metric": "grade_3_direct_answer_hit",
            "runtime_minus_raw_top_1_hits": (
                runtime_direct_metrics["top_1_hits"] - raw_direct_metrics["top_1_hits"]
            ),
            "runtime_minus_raw_top_3_hits": (
                runtime_direct_metrics["top_3_hits"] - raw_direct_metrics["top_3_hits"]
            ),
            "fused_minus_raw_top_1_hits": (
                fused_direct_metrics["top_1_hits"] - raw_direct_metrics["top_1_hits"]
            ),
            "fused_minus_raw_top_3_hits": (
                fused_direct_metrics["top_3_hits"] - raw_direct_metrics["top_3_hits"]
            ),
            "fused_minus_feature_only_top_1_hits": (
                fused_direct_metrics["top_1_hits"] - runtime_direct_metrics["top_1_hits"]
            ),
            "fused_minus_feature_only_top_3_hits": (
                fused_direct_metrics["top_3_hits"] - runtime_direct_metrics["top_3_hits"]
            ),
            "interpretation": (
                "These deltas compare direct input, lossy feature-only rewriting, and "
                "sanitized original plus deterministic RetrievalIntent query fusion. "
                "A hit now requires a paired title/section grade-3 judgment. "
                "This is not a live-LLM evaluation."
            ),
        },
        "bge_evaluation": bge_evaluation,
        "limitations": limitations,
    }


def run_keyword_evaluation(
    *,
    chunks_path: str | Path,
    eval_queries_path: str | Path,
    top_k: int = 3,
    candidate_top_k: int = 5,
    rrf_k: int = 60,
    timer: Callable[[], float] = time.perf_counter,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Compare frozen query paths using the deterministic offline provider."""

    return _run_evaluation(
        chunks_path=chunks_path,
        eval_queries_path=eval_queries_path,
        provider=KeywordEmbeddingProvider(),
        backend="keyword_rrf",
        network_access_required=False,
        retrieval_pipeline_version=RETRIEVAL_PIPELINE_VERSION,
        pipeline_description=("BM25 + keyword feature vectors + reciprocal rank fusion"),
        bge_evaluation={
            "status": "historical_not_rerun",
            "current_metrics": None,
            "note": (
                "No BGE service was started for this evaluation. No historical BGE number "
                "is presented as a current result."
            ),
        },
        limitations=[
            "KeywordEmbeddingProvider is deterministic and is not a semantic model.",
            "The manually curated 18-query dataset does not represent real customer traffic.",
            "Unjudged results are treated as grade 0 until the label pool is expanded.",
            "Runtime-rule evaluation uses synthetic valid leads with an empty company name.",
            "LiveFeatureExtractor and a real LLM are not evaluated in this report.",
            "The original-query sanitizer removes obvious contact data but is not a full PII detector.",
            "Retrieval quality does not affect LeadDecision.",
        ],
        prewarm_query_embeddings=False,
        top_k=top_k,
        candidate_top_k=candidate_top_k,
        rrf_k=rrf_k,
        timer=timer,
        generated_at=generated_at,
    )


def run_bge_evaluation(
    *,
    chunks_path: str | Path,
    eval_queries_path: str | Path,
    base_url: str = DEFAULT_BGE_API_BASE_URL,
    model_name: str = DEFAULT_BGE_EMBEDDING_MODEL,
    timeout: float = 60.0,
    embedding_provider: EmbeddingProvider | None = None,
    top_k: int = 3,
    candidate_top_k: int = 5,
    rrf_k: int = 60,
    timer: Callable[[], float] = time.perf_counter,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Compare frozen query paths using BGE-M3 dense embeddings plus BM25."""

    owns_provider = embedding_provider is None
    provider = embedding_provider or BgeM3EmbeddingProvider(
        base_url=base_url,
        model_name=model_name,
        timeout=timeout,
    )
    try:
        return _run_evaluation(
            chunks_path=chunks_path,
            eval_queries_path=eval_queries_path,
            provider=provider,
            backend="bge_rrf",
            network_access_required=True,
            retrieval_pipeline_version=BGE_RETRIEVAL_PIPELINE_VERSION,
            pipeline_description=("BM25 + BGE-M3 dense vectors + reciprocal rank fusion"),
            bge_evaluation={
                "status": "completed",
                "current_metrics": "evaluations",
                "model": provider.model_name,
                "note": (
                    "Current metrics were generated with the v4 paired graded-relevance "
                    "contract; they are not copied from a historical report."
                ),
            },
            limitations=[
                "The manually curated 18-query dataset does not represent real customer traffic.",
                "Unjudged results are treated as grade 0 until the label pool is expanded.",
                "Runtime-rule evaluation uses synthetic valid leads with an empty company name.",
                "LiveFeatureExtractor and a real LLM are not evaluated in this report.",
                "The original-query sanitizer removes obvious contact data but is not a full PII detector.",
                "The evaluation depends on an external embedding API and its current model version.",
                "Retrieval quality does not affect LeadDecision.",
            ],
            prewarm_query_embeddings=True,
            top_k=top_k,
            candidate_top_k=candidate_top_k,
            rrf_k=rrf_k,
            timer=timer,
            generated_at=generated_at,
        )
    finally:
        if owns_provider and isinstance(provider, BgeM3EmbeddingProvider):
            provider.close()


def write_evaluation_report(report: dict[str, Any], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
