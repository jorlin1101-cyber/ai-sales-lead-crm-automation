import json
from pathlib import Path
from typing import Any

from lead_cleaner.rag.chunker import chunk_documents_by_heading_sections
from lead_cleaner.rag.schemas import KnowledgeChunk, KnowledgeDocument


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "knowledge_snapshot" / "notion_pages.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "knowledge_snapshot" / "knowledge_chunks.json"


def load_knowledge_documents(input_path: Path) -> list[KnowledgeDocument]:
    if not input_path.exists():
        raise FileNotFoundError(f"Knowledge documents file not found: {input_path}")

    raw_data = json.loads(input_path.read_text(encoding="utf-8"))

    if not isinstance(raw_data, list):
        raise ValueError("Knowledge documents file must contain a JSON list.")

    return [KnowledgeDocument(**item) for item in raw_data]


def knowledge_chunk_to_dict(chunk: KnowledgeChunk) -> dict[str, Any]:

    return chunk.model_dump(mode="json")


def save_knowledge_chunks(
    chunks: list[KnowledgeChunk],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    serialized_chunks = [knowledge_chunk_to_dict(chunk) for chunk in chunks]

    output_path.write_text(
        json.dumps(
            serialized_chunks,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    documents = load_knowledge_documents(DEFAULT_INPUT_PATH)

    chunks = chunk_documents_by_heading_sections(documents)

    save_knowledge_chunks(
        chunks=chunks,
        output_path=DEFAULT_OUTPUT_PATH,
    )

    print("Built knowledge chunks.")
    print(f"Documents: {len(documents)}")
    print(f"Chunks: {len(chunks)}")
    print(f"Output: {DEFAULT_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
