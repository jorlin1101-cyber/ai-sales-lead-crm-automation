from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.lead import KnowledgeSource


def sanitize_retrieved_sources(
    chunks: list[RetrievedChunk],
    *,
    top_k: int = 3,
) -> list[KnowledgeSource]:
    """Expose only the four public source fields allowed by the API contract."""

    if top_k < 1 or top_k > 3:
        raise ValueError("top_k must be between 1 and 3")

    sources: list[KnowledgeSource] = []
    seen_chunk_ids: set[str] = set()

    for chunk in chunks:
        if chunk.chunk_id in seen_chunk_ids:
            continue

        seen_chunk_ids.add(chunk.chunk_id)
        sources.append(
            KnowledgeSource(
                chunk_id=chunk.chunk_id,
                source_title=chunk.source_title,
                section=chunk.section,
                rank=len(sources) + 1,
            )
        )

        if len(sources) == top_k:
            break

    return sources
