import json
from pathlib import Path

from lead_cleaner.rag.bm25_retriever import build_bm25_index
from lead_cleaner.rag.demo_embedding_provider import KeywordEmbeddingProvider
from lead_cleaner.rag.dense_retriever import build_dense_index
from lead_cleaner.rag.eval_runner import has_expected_match, evaluate_match_detail
from lead_cleaner.rag.eval_schemas import RagEvalCase
from lead_cleaner.rag.hybrid_retriever import retrieve_hybrid
from lead_cleaner.rag.schemas import KnowledgeChunk, RetrievedChunk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHUNKS_PATH = (
    PROJECT_ROOT / "data" / "knowledge_snapshot" / "knowledge_chunks.json"
)
DEFAULT_EVAL_QUERIES_PATH = PROJECT_ROOT / "data" / "rag_eval" / "eval_queries.json"


def load_knowledge_chunks(chunks_path: Path) -> list[KnowledgeChunk]:
    if not chunks_path.exists():
        raise FileNotFoundError(f"Knowledge chunks file not found: {chunks_path}")

    raw_chunks = json.loads(chunks_path.read_text(encoding="utf-8"))

    if not isinstance(raw_chunks, list):
        raise ValueError("Knowledge chunks file must contain a JSON list.")

    return [KnowledgeChunk(**item) for item in raw_chunks]


def load_eval_cases(eval_queries_path: Path) -> list[RagEvalCase]:
    if not eval_queries_path.exists():
        raise FileNotFoundError(f"Eval queries file not found: {eval_queries_path}")

    raw_eval_cases = json.loads(eval_queries_path.read_text(encoding="utf-8"))

    if not isinstance(raw_eval_cases, list):
        raise ValueError("Eval queries file must contain a JSON list.")

    return [RagEvalCase(**item) for item in raw_eval_cases]


def print_retrieved_results(
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
            f"doc_type_hit={detail.doc_type_hit} | "
            f"region_hit={detail.region_hit} | "
            f"source_title_hit={detail.source_title_hit} | "
            f"section_hit={detail.section_hit} | "
            f"overall_match={detail.overall_match}"
        )


def main() -> None:
    eval_cases = load_eval_cases(DEFAULT_EVAL_QUERIES_PATH)
    chunks = load_knowledge_chunks(DEFAULT_CHUNKS_PATH)

    provider = KeywordEmbeddingProvider()
    bm25_index = build_bm25_index(chunks)
    dense_index = build_dense_index(
        chunks=chunks,
        embedding_provider=provider,
    )

    top_1_hits = 0
    top_3_hits = 0

    print("Loaded eval cases:", len(eval_cases))
    print("Loaded chunks:", len(chunks))
    print("Embedding provider:", provider.model_name)
    print(
        "\nNOTE: This eval uses KeywordEmbeddingProvider. "
        "It validates retrieval pipeline behavior, not real semantic quality."
    )

    for eval_case in eval_cases:
        results = retrieve_hybrid(
            query=eval_case.query,
            bm25_index=bm25_index,
            dense_index=dense_index,
            embedding_provider=provider,
            top_k=3,
            candidate_top_k=5,
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

        print("\n" + "=" * 100)
        print(f"Query ID: {eval_case.query_id}")
        print(f"Query: {eval_case.query}")
        print(f"Expected doc_type: {eval_case.expected_doc_type}")
        print(f"Expected region: {eval_case.expected_region}")
        print(f"Expected source_titles: {eval_case.expected_source_titles}")
        print(f"Expected sections: {eval_case.expected_sections}")
        print(f"top_1_hit: {top_1_hit}")
        print(f"top_3_hit: {top_3_hit}")
        print("Results:")
        print_retrieved_results(results=results, eval_case=eval_case)

    total = len(eval_cases)

    print("\n" + "=" * 100)
    print("SUMMARY")
    print(f"Total eval cases: {total}")
    print(f"Top 1 hits: {top_1_hits}/{total}")
    print(f"Top 3 hits: {top_3_hits}/{total}")
    print(f"Top 1 hit rate: {top_1_hits / total:.2%}")
    print(f"Top 3 hit rate: {top_3_hits / total:.2%}")


if __name__ == "__main__":
    main()
