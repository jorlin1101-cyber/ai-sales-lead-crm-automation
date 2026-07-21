from pathlib import Path

from pydantic import TypeAdapter

from lead_cleaner.rag.schemas import KnowledgeChunk


_knowledge_chunk_list_adapter = TypeAdapter(list[KnowledgeChunk])


def load_knowledge_chunks(path: str | Path) -> list[KnowledgeChunk]:
    """Load and validate the public knowledge snapshot used at runtime."""

    snapshot_path = Path(path)
    snapshot_text = snapshot_path.read_text(encoding="utf-8")
    chunks = _knowledge_chunk_list_adapter.validate_json(snapshot_text)

    if not chunks:
        raise ValueError("Knowledge chunks snapshot cannot be empty.")

    chunk_ids = [chunk.chunk_id for chunk in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("Knowledge chunks snapshot contains duplicate chunk_id values.")

    return chunks
