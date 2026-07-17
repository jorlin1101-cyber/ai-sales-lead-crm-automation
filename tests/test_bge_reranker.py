import json

import httpx
import pytest

from lead_cleaner.rag.bge_reranker import BgeReranker, build_rerank_document_text
from lead_cleaner.rag.schemas import RetrievedChunk


def make_retrieved_chunk(
    chunk_id: str,
    source_title: str,
    section: str,
    text: str,
    rank: int,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_type="notion_page",
        notion_page_id=f"page_{chunk_id}",
        source_title=source_title,
        source_path=f"Knowledge / {source_title}",
        doc_type="product",
        region="tibet",
        product_name=source_title,
        section=section,
        text=text,
        score=1.0 / rank,
        rank=rank,
        retrieval_source="fusion",
    )


def test_build_rerank_document_text_includes_metadata_and_text() -> None:
    chunk = make_retrieved_chunk(
        chunk_id="chunk_1",
        source_title="Tibet Cultural Tour",
        section="Suitable For",
        text="This trip is suitable for deeper cultural interests.",
        rank=1,
    )

    document_text = build_rerank_document_text(chunk)

    assert "Title: Tibet Cultural Tour" in document_text
    assert "Section: Suitable For" in document_text
    assert "Document type: product" in document_text
    assert "Region: tibet" in document_text
    assert "Product: Tibet Cultural Tour" in document_text
    assert "Content:" in document_text
    assert "This trip is suitable for deeper cultural interests." in document_text


def test_bge_reranker_posts_expected_payload_and_orders_by_relevance_score() -> None:
    captured: dict[str, object] = {}

    candidates = [
        make_retrieved_chunk(
            chunk_id="chunk_1",
            source_title="Tibet Destination Overview",
            section="Best For",
            text="Best for travelers deciding whether Tibet is suitable.",
            rank=1,
        ),
        make_retrieved_chunk(
            chunk_id="chunk_2",
            source_title="Tibet Cultural Tour",
            section="Suitable For",
            text="Suitable for travelers seeking a deeper Tibetan cultural journey.",
            rank=2,
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content.decode("utf-8"))

        return httpx.Response(
            status_code=200,
            json={
                "id": "rerank-test",
                "results": [
                    {
                        "index": 0,
                        "relevance_score": 0.42,
                    },
                    {
                        "index": 1,
                        "relevance_score": 0.91,
                    },
                ],
                "meta": {
                    "tokens": {
                        "input_tokens": 100,
                    }
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reranker = BgeReranker(
        base_url="http://testserver/v1",
        client=client,
    )

    results = reranker.rerank(
        query="deeper Tibetan cultural journey",
        candidates=candidates,
        top_k=5,
    )

    payload = captured["payload"]

    assert captured["url"] == "http://testserver/v1/rerank"
    assert isinstance(payload, dict)
    assert payload["model"] == "BAAI/bge-reranker-v2-m3"
    assert payload["query"] == "deeper Tibetan cultural journey"
    assert payload["return_documents"] is False
    assert payload["top_n"] == 2
    assert len(payload["documents"]) == 2

    assert [result.chunk_id for result in results] == ["chunk_2", "chunk_1"]
    assert [result.rank for result in results] == [1, 2]
    assert [result.score for result in results] == [0.91, 0.42]
    assert all(result.retrieval_source == "rerank" for result in results)


def test_bge_reranker_uses_original_rank_as_tie_breaker() -> None:
    candidates = [
        make_retrieved_chunk(
            chunk_id="chunk_a",
            source_title="Tibet Cultural Tour",
            section="Pricing Notes",
            text="Pricing depends on season and hotel level.",
            rank=3,
        ),
        make_retrieved_chunk(
            chunk_id="chunk_b",
            source_title="Tibet Cultural Tour",
            section="Suitable For",
            text="Suitable for travelers seeking a deeper Tibetan cultural journey.",
            rank=1,
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "results": [
                    {
                        "index": 0,
                        "relevance_score": 0.8,
                    },
                    {
                        "index": 1,
                        "relevance_score": 0.8,
                    },
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reranker = BgeReranker(
        base_url="http://testserver/v1",
        client=client,
    )

    results = reranker.rerank(
        query="deeper Tibetan cultural journey",
        candidates=candidates,
        top_k=2,
    )

    assert [result.chunk_id for result in results] == ["chunk_b", "chunk_a"]


def test_bge_reranker_returns_empty_for_empty_candidates() -> None:
    reranker = BgeReranker(base_url="http://testserver/v1")

    assert reranker.rerank(
        query="hello",
        candidates=[],
        top_k=3,
    ) == []


def test_bge_reranker_returns_empty_for_blank_query() -> None:
    candidates = [
        make_retrieved_chunk(
            chunk_id="chunk_1",
            source_title="Tibet Cultural Tour",
            section="Suitable For",
            text="Suitable for cultural travelers.",
            rank=1,
        )
    ]

    reranker = BgeReranker(base_url="http://testserver/v1")

    assert reranker.rerank(
        query="   ",
        candidates=candidates,
        top_k=3,
    ) == []


def test_bge_reranker_raises_for_invalid_top_k() -> None:
    reranker = BgeReranker(base_url="http://testserver/v1")

    with pytest.raises(ValueError):
        reranker.rerank(
            query="hello",
            candidates=[],
            top_k=0,
        )


def test_bge_reranker_raises_for_http_error() -> None:
    candidates = [
        make_retrieved_chunk(
            chunk_id="chunk_1",
            source_title="Tibet Cultural Tour",
            section="Suitable For",
            text="Suitable for cultural travelers.",
            rank=1,
        )
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=500,
            json={"detail": "upstream failed"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reranker = BgeReranker(
        base_url="http://testserver/v1",
        client=client,
    )

    with pytest.raises(RuntimeError):
        reranker.rerank(
            query="hello",
            candidates=candidates,
            top_k=1,
        )


def test_bge_reranker_raises_for_missing_results_list() -> None:
    candidates = [
        make_retrieved_chunk(
            chunk_id="chunk_1",
            source_title="Tibet Cultural Tour",
            section="Suitable For",
            text="Suitable for cultural travelers.",
            rank=1,
        )
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"object": "rerank"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reranker = BgeReranker(
        base_url="http://testserver/v1",
        client=client,
    )

    with pytest.raises(RuntimeError):
        reranker.rerank(
            query="hello",
            candidates=candidates,
            top_k=1,
        )


def test_bge_reranker_raises_for_invalid_result_index() -> None:
    candidates = [
        make_retrieved_chunk(
            chunk_id="chunk_1",
            source_title="Tibet Cultural Tour",
            section="Suitable For",
            text="Suitable for cultural travelers.",
            rank=1,
        )
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "results": [
                    {
                        "index": 99,
                        "relevance_score": 0.9,
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reranker = BgeReranker(
        base_url="http://testserver/v1",
        client=client,
    )

    with pytest.raises(RuntimeError):
        reranker.rerank(
            query="hello",
            candidates=candidates,
            top_k=1,
        )


def test_bge_reranker_raises_for_non_numeric_relevance_score() -> None:
    candidates = [
        make_retrieved_chunk(
            chunk_id="chunk_1",
            source_title="Tibet Cultural Tour",
            section="Suitable For",
            text="Suitable for cultural travelers.",
            rank=1,
        )
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "results": [
                    {
                        "index": 0,
                        "relevance_score": "high",
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reranker = BgeReranker(
        base_url="http://testserver/v1",
        client=client,
    )

    with pytest.raises(RuntimeError):
        reranker.rerank(
            query="hello",
            candidates=candidates,
            top_k=1,
        )
