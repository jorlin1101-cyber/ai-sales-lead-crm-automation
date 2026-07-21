from typing import Any

import httpx

from lead_cleaner.rag.bge_embedding_provider import DEFAULT_BGE_API_BASE_URL
from lead_cleaner.rag.schemas import RetrievedChunk


DEFAULT_BGE_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


def build_rerank_document_text(chunk: RetrievedChunk) -> str:
    parts = [
        f"Title: {chunk.source_title}",
        f"Section: {chunk.section}",
        f"Document type: {chunk.doc_type}",
        f"Region: {chunk.region}",
    ]

    if chunk.product_name:
        parts.append(f"Product: {chunk.product_name}")

    parts.append("Content:")
    parts.append(chunk.text)

    return "\n".join(parts)


class BgeReranker:
    """
    Reranker backed by a SiliconFlow-compatible BGE rerank API.

    Expected endpoint:
    POST {base_url}/rerank

    Expected response path:
    response["results"][i]["index"]
    response["results"][i]["relevance_score"]
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BGE_API_BASE_URL,
        model_name: str = DEFAULT_BGE_RERANK_MODEL,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)

    def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        if top_k <= 0:
            raise ValueError("top_k must be greater than 0.")

        if not query.strip():
            return []

        if not candidates:
            return []

        documents = [build_rerank_document_text(candidate) for candidate in candidates]
        top_n = min(top_k, len(candidates))

        response = self._client.post(
            f"{self.base_url}/rerank",
            json={
                "model": self.model_name,
                "query": query,
                "documents": documents,
                "return_documents": False,
                "top_n": top_n,
            },
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"BGE rerank request failed with status "
                f"{exc.response.status_code}: {exc.response.text}"
            ) from exc

        payload = response.json()

        return self._build_reranked_chunks(
            payload=payload,
            candidates=candidates,
        )

    @staticmethod
    def _build_reranked_chunks(
        payload: dict[str, Any],
        candidates: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        results = payload.get("results")

        if not isinstance(results, list):
            raise RuntimeError("BGE rerank response must contain a results list.")

        scored_candidates: list[tuple[RetrievedChunk, float]] = []

        for item in results:
            if not isinstance(item, dict):
                raise RuntimeError("Each rerank response item must be an object.")

            index = item.get("index")
            relevance_score = item.get("relevance_score")

            if not isinstance(index, int):
                raise RuntimeError("Rerank response item must contain integer index.")

            if index < 0 or index >= len(candidates):
                raise RuntimeError(f"Rerank response index out of range: {index}")

            if not isinstance(relevance_score, int | float):
                raise RuntimeError("Rerank response item must contain numeric relevance_score.")

            scored_candidates.append(
                (
                    candidates[index],
                    float(relevance_score),
                )
            )

        scored_candidates.sort(key=lambda item: (-item[1], item[0].rank, item[0].chunk_id))

        return [
            _copy_as_rerank_result(
                chunk=chunk,
                score=score,
                rank=rank,
            )
            for rank, (chunk, score) in enumerate(scored_candidates, start=1)
        ]


def _copy_as_rerank_result(
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
        retrieval_source="rerank",
    )
