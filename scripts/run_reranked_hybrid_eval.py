import json
from pathlib import Path

from lead_cleaner.rag.bge_embedding_provider import BgeM3EmbeddingProvider
from lead_cleaner.rag.bge_reranker import BgeReranker
from lead_cleaner.rag.bm25_retriever import build_bm25_index
from lead_cleaner.rag.dense_retriever import build_dense_index
from lead_cleaner.rag.eval_runner import evaluate_match_detail, has_expected_match
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

        print(
            f"    {result.rank}. "
            f"score={result.score:.6f} | "
            f"{result.doc_type} | "
            f"{result.region} | "
            f"{result.source_title} | "
            f"{result.section} | "
            f"source={result.retrieval_source} | "
            f"doc_type_hit={detail.doc_type_hit} | "
            f"region_hit={detail.region_hit} | "
            f"source_title_hit={detail.source_title_hit} | "
            f"section_hit={detail.section_hit} | "
            f"overall_match={detail.overall_match}"
        )


def main() -> None:
    chunks = load_chunks(CHUNKS_PATH)
    eval_cases = load_eval_cases(EVAL_CASES_PATH)

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
        print("=" * 100)
        print(f"Query ID: {eval_case.query_id}")
        print(f"Query: {eval_case.query}")
        print(
            "Expected: "
            f"doc_type={eval_case.expected_doc_type}, "
            f"region={eval_case.expected_region}, "
            f"titles={eval_case.expected_source_titles}, "
            f"sections={eval_case.expected_sections}"
        )

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

        top_1_hit = has_expected_match(
            results=results,
            eval_case=eval_case,
            top_k=1,
        )
        top_3_hit = has_expected_match(
            results=results,
            eval_case=eval_case,
            top_k=3,
        )

        if top_1_hit:
            top_1_hits += 1

        if top_3_hit:
            top_3_hits += 1

        print(f"Top 1 hit: {top_1_hit}")
        print(f"Top 3 hit: {top_3_hit}")
        print("Results:")
        print_results(results=results, eval_case=eval_case)
        print()

    total = len(eval_cases)

    print("=" * 100)
    print("Summary")
    print(f"Top 1 hits: {top_1_hits}/{total} = {top_1_hits / total:.2%}")
    print(f"Top 3 hits: {top_3_hits}/{total} = {top_3_hits / total:.2%}")


if __name__ == "__main__":
    main()
