import json
from pathlib import Path

from lead_cleaner.rag.bm25_retriever import build_bm25_index, retrieve_bm25
from lead_cleaner.rag.dense_retriever import build_dense_index, retrieve_dense
from lead_cleaner.rag.hybrid_retriever import retrieve_hybrid
from lead_cleaner.rag.demo_embedding_provider import KeywordEmbeddingProvider
from lead_cleaner.rag.schemas import KnowledgeChunk, RetrievedChunk


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "data" / "knowledge_snapshot" / "knowledge_chunks.json"


DEMO_QUERIES = [
    "Tibet permit payment",
    "20 people private quotation",
    "a meaningful cultural journey in Tibetan areas",
    "Yunnan family travel",
    "川西 私人 定制 报价",
]


def load_knowledge_chunks(chunks_path: Path) -> list[KnowledgeChunk]:
    if not chunks_path.exists():
        raise FileNotFoundError(f"Knowledge chunks file not found: {chunks_path}")

    raw_chunks = json.loads(chunks_path.read_text(encoding="utf-8"))

    if not isinstance(raw_chunks, list):
        raise ValueError("Knowledge chunks file must contain a JSON list.")

    return [KnowledgeChunk(**item) for item in raw_chunks]


def print_results(title: str, results: list[RetrievedChunk]) -> None:
    print(f"\n{title}")

    if not results:
        print("  No results.")
        return

    for result in results:
        print(
            f"  {result.rank}. "
            f"score={result.score:.6f} | "
            f"{result.retrieval_source} | "
            f"{result.doc_type} | "
            f"{result.region} | "
            f"{result.source_title} | "
            f"{result.section}"
        )


def main() -> None:
    chunks = load_knowledge_chunks(DEFAULT_CHUNKS_PATH)
    provider = KeywordEmbeddingProvider()

    bm25_index = build_bm25_index(chunks)
    dense_index = build_dense_index(
        chunks=chunks,
        embedding_provider=provider,
    )

    print("Loaded chunks:", len(chunks))
    print("BM25 index documents:", len(bm25_index.chunks))
    print("Dense index documents:", len(dense_index.chunks))
    print("Dense embedding provider:", dense_index.embedding_model)
    print("Dense vector dimension:", dense_index.vector_dimension)
    print(
        "\nNOTE: KeywordEmbeddingProvider is for pipeline demo only. "
        "It is not a real semantic embedding model."
    )

    for query in DEMO_QUERIES:
        print("\n" + "=" * 100)
        print("QUERY:", query)

        bm25_results = retrieve_bm25(
            query=query,
            index=bm25_index,
            top_k=3,
        )
        dense_results = retrieve_dense(
            query=query,
            index=dense_index,
            embedding_provider=provider,
            top_k=3,
        )
        hybrid_results = retrieve_hybrid(
            query=query,
            bm25_index=bm25_index,
            dense_index=dense_index,
            embedding_provider=provider,
            top_k=3,
            candidate_top_k=5,
        )

        print_results("BM25 results", bm25_results)
        print_results("Dense results", dense_results)
        print_results("Hybrid fusion results", hybrid_results)


if __name__ == "__main__":
    main()
