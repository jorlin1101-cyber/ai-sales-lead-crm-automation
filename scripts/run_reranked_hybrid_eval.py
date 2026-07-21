import json
from pathlib import Path

from lead_cleaner.rag.bge_embedding_provider import BgeM3EmbeddingProvider
from lead_cleaner.rag.bge_reranker import BgeReranker
from lead_cleaner.rag.bm25_retriever import build_bm25_index
from lead_cleaner.rag.dense_retriever import build_dense_index
from lead_cleaner.rag.eval_runner import (
    evaluate_match_detail,
    has_expected_match,
    validate_eval_cases_against_chunks,
)
from lead_cleaner.rag.eval_schemas import RagEvalCase
from lead_cleaner.rag.reranked_hybrid_retriever import retrieve_reranked_hybrid
from lead_cleaner.rag.schemas import KnowledgeChunk, RetrievedChunk


CHUNKS_PATH = Path("data/knowledge_snapshot/knowledge_chunks.json")
EVAL_CASES_PATH = Path("data/rag_eval/eval_queries.json")


def load_chunks(path: Path) -> list[KnowledgeChunk]:
    raw_items = json.loads(path.read_text(encoding="utf-8"))
    return [KnowledgeChunk(**item) for item in raw_items]


def load_eval_cases(path: Path) -> list[RagEvalCase]:
    raw_items = json.loads(path.read_text(encoding="utf-8"))
    return [RagEvalCase(**item) for item in raw_items]


def print_results(
    results: list[RetrievedChunk],
    eval_case: RagEvalCase,
) -> None:
    for result in results:
        detail = evaluate_match_detail(result=result, eval_case=eval_case)
        facets = ",".join(detail.covers_facets) or "-"
        print(
            f"    {result.rank}. "
            f"score={result.score:.6f} | "
            f"{result.doc_type} | "
            f"{result.region} | "
            f"{result.source_title} | "
            f"{result.section} | "
            f"source={result.retrieval_source} | "
            f"grade={detail.relevance_grade} | "
            f"judged={detail.judged} | "
            f"relevant={detail.relevant_match} | "
            f"direct={detail.direct_match} | "
            f"source_match={detail.source_match} | "
            f"facets={facets}"
        )


def main() -> None:
    chunks = load_chunks(CHUNKS_PATH)
    eval_cases = load_eval_cases(EVAL_CASES_PATH)
    validate_eval_cases_against_chunks(eval_cases, chunks)

    embedding_provider = BgeM3EmbeddingProvider()
    reranker = BgeReranker()

    print(f"Loaded chunks: {len(chunks)}")
    print(f"Loaded eval cases: {len(eval_cases)}")
    print(f"Embedding model: {embedding_provider.model_name}")
    print(f"Rerank model: {reranker.model_name}")
    print("Building BM25 index...")
    bm25_index = build_bm25_index(chunks)

    print("Building BGE-M3 dense index...")
    dense_index = build_dense_index(
        chunks=chunks,
        embedding_provider=embedding_provider,
    )

    print(f"Dense vector dimension: {dense_index.vector_dimension}")
    print()

    top_1_hits = 0
    top_3_hits = 0

    for eval_case in eval_cases:
        direct_targets = [
            f"{judgment.source_title} / {judgment.section}"
            for judgment in eval_case.judgments
            if judgment.relevance_grade == 3
        ]
        print("=" * 100)
        print(f"Query ID: {eval_case.query_id}")
        print(f"Query: {eval_case.query}")
        print(f"Facets: {[facet.facet_id for facet in eval_case.facets]}")
        print(f"Grade-3 direct targets: {direct_targets}")

        results = retrieve_reranked_hybrid(
            query=eval_case.query,
            bm25_index=bm25_index,
            dense_index=dense_index,
            embedding_provider=embedding_provider,
            reranker=reranker,
            top_k=3,
            rrf_candidate_top_k=20,
            rerank_candidate_top_k=10,
        )

        top_1_hit = has_expected_match(results, eval_case, top_k=1)
        top_3_hit = has_expected_match(results, eval_case, top_k=3)
        top_1_hits += int(top_1_hit)
        top_3_hits += int(top_3_hit)

        print(f"Direct Top 1 hit: {top_1_hit}")
        print(f"Direct Top 3 hit: {top_3_hit}")
        print("Results:")
        print_results(results=results, eval_case=eval_case)
        print()

    total = len(eval_cases)
    print("=" * 100)
    print("Summary")
    print(f"Direct Top 1 hits: {top_1_hits}/{total} = {top_1_hits / total:.2%}")
    print(f"Direct Top 3 hits: {top_3_hits}/{total} = {top_3_hits / total:.2%}")


if __name__ == "__main__":
    main()
