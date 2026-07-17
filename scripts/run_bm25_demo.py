import json
from pathlib import Path

from lead_cleaner.rag.bm25_retriever import (
    build_bm25_index,
    expand_query_tokens,
    retrieve_bm25,
    tokenize,
)
from lead_cleaner.rag.schemas import KnowledgeChunk


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHUNKS_PATH = (
    PROJECT_ROOT / "data" / "knowledge_snapshot" / "knowledge_chunks.json"
)


DEMO_QUERIES = [
    "20 people private quotation",
    "Tibet permit payment",
    "western Sichuan private tour",
    "hotel level vehicle type guide requirement",
    "Yunnan family tour",
    "川西 私人 定制 报价",
]


def load_knowledge_chunks(chunks_path: Path) -> list[KnowledgeChunk]:
    if not chunks_path.exists():
        raise FileNotFoundError(f"Knowledge chunks file not found: {chunks_path}")

    raw_chunks = json.loads(chunks_path.read_text(encoding="utf-8"))

    if not isinstance(raw_chunks, list):
        raise ValueError("Knowledge chunks file must contain a JSON list.")

    return [KnowledgeChunk(**item) for item in raw_chunks]


def print_results_for_query(
    query: str,
    index,
    top_k: int = 3,
) -> None:
    print("=" * 80)
    print(f"QUERY: {query}")
    print(f"TOKENS: {tokenize(query)}")
    print(f"EXPANDED: {expand_query_tokens(tokenize(query))}")

    results = retrieve_bm25(
        query=query,
        index=index,
        top_k=top_k,
    )

    if not results:
        print("No results.")
        return

    for result in results:
        print(
            result.rank,
            "| score=", round(result.score, 4),
            "|", result.doc_type,
            "|", result.region,
            "|", result.source_title,
            "|", result.section,
        )


def main() -> None:
    chunks = load_knowledge_chunks(DEFAULT_CHUNKS_PATH)
    index = build_bm25_index(chunks)

    print("Loaded chunks:", len(chunks))
    print("BM25 index documents:", len(index.chunks))

    for query in DEMO_QUERIES:
        print_results_for_query(
            query=query,
            index=index,
            top_k=3,
        )


if __name__ == "__main__":
    main()
