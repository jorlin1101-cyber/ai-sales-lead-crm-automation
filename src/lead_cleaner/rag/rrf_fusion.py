from lead_cleaner.rag.schemas import RetrievedChunk


DEFAULT_RRF_K = 60


def rrf_score(rank: int, k: int = DEFAULT_RRF_K) -> float:
    if rank < 1:
        raise ValueError("rank must be greater than 0.")

    if k < 0:
        raise ValueError("k must not be negative.")

    return 1 / (k + rank)


def _copy_as_fusion_result(
    chunk: RetrievedChunk,
    score: float,
    rank: int,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.chunk_id,
        source_type=chunk.source_type,
        notion_page_id=chunk.notion_page_id,
        source_title=chunk.source_title,
        source_path=chunk.source_path,
        doc_type=chunk.doc_type,
        region=chunk.region,
        product_name=chunk.product_name,
        section=chunk.section,
        text=chunk.text,
        score=score,
        rank=rank,
        retrieval_source="fusion",
    )


def fuse_retrieved_chunks(
    result_lists: list[list[RetrievedChunk]],
    top_k: int = 5,
    k: int = DEFAULT_RRF_K,
) -> list[RetrievedChunk]:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")

    if k < 0:
        raise ValueError("k must not be negative.")

    fusion_scores: dict[str, float] = {}
    representative_chunks: dict[str, RetrievedChunk] = {}

    for results in result_lists:
        for result in results:
            fusion_scores[result.chunk_id] = fusion_scores.get(result.chunk_id, 0.0) + rrf_score(
                rank=result.rank, k=k
            )

            if result.chunk_id not in representative_chunks:
                representative_chunks[result.chunk_id] = result

    sorted_chunk_ids = sorted(
        fusion_scores,
        key=lambda chunk_id: (-fusion_scores[chunk_id], chunk_id),
    )

    top_chunk_ids = sorted_chunk_ids[:top_k]

    return [
        _copy_as_fusion_result(
            chunk=representative_chunks[chunk_id],
            score=fusion_scores[chunk_id],
            rank=rank,
        )
        for rank, chunk_id in enumerate(top_chunk_ids, start=1)
    ]
