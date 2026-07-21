import json

import httpx
import pytest

from lead_cleaner.rag.bge_embedding_provider import (
    DEFAULT_BGE_API_BASE_URL,
    BgeM3EmbeddingProvider,
)


def test_bge_default_port_does_not_conflict_with_fastapi() -> None:
    assert DEFAULT_BGE_API_BASE_URL == "http://127.0.0.1:8001/v1"


def test_bge_embedding_provider_posts_expected_payload_and_orders_by_index() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content.decode("utf-8"))

        return httpx.Response(
            status_code=200,
            json={
                "object": "list",
                "model": "BAAI/bge-m3",
                "data": [
                    {
                        "object": "embedding",
                        "embedding": [0.3, 0.4],
                        "index": 1,
                    },
                    {
                        "object": "embedding",
                        "embedding": [0.1, 0.2],
                        "index": 0,
                    },
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "total_tokens": 10,
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = BgeM3EmbeddingProvider(
        base_url="http://testserver/v1",
        client=client,
    )

    vectors = provider.embed_texts(["text A", "text B"])

    assert captured["url"] == "http://testserver/v1/embeddings"
    assert captured["payload"] == {
        "model": "BAAI/bge-m3",
        "input": ["text A", "text B"],
        "encoding_format": "float",
    }
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


def test_bge_embedding_provider_embed_text_returns_single_vector() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "object": "list",
                "model": "BAAI/bge-m3",
                "data": [
                    {
                        "object": "embedding",
                        "embedding": [0.1, 0.2, 0.3],
                        "index": 0,
                    }
                ],
                "usage": {},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = BgeM3EmbeddingProvider(
        base_url="http://testserver/v1",
        client=client,
    )

    vector = provider.embed_text("hello")

    assert vector == [0.1, 0.2, 0.3]


def test_bge_embedding_provider_returns_empty_list_for_empty_batch() -> None:
    provider = BgeM3EmbeddingProvider(base_url="http://testserver/v1")

    assert provider.embed_texts([]) == []


def test_bge_embedding_provider_raises_for_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=500,
            json={"detail": "upstream failed"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = BgeM3EmbeddingProvider(
        base_url="http://testserver/v1",
        client=client,
    )

    with pytest.raises(RuntimeError):
        provider.embed_text("hello")


def test_bge_embedding_provider_raises_for_missing_embedding_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"object": "list", "data": []},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = BgeM3EmbeddingProvider(
        base_url="http://testserver/v1",
        client=client,
    )

    with pytest.raises(RuntimeError):
        provider.embed_text("hello")


def test_bge_embedding_provider_closes_owned_http_client() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    provider = BgeM3EmbeddingProvider(client=client)

    provider.close()

    assert client.is_closed is True
