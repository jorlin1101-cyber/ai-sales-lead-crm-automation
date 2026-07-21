from typing import Any

import httpx


DEFAULT_BGE_API_BASE_URL = "http://127.0.0.1:8001/v1"
DEFAULT_BGE_EMBEDDING_MODEL = "BAAI/bge-m3"


class BgeM3EmbeddingProvider:
    """
    Embedding provider backed by a SiliconFlow-compatible BGE-M3 API.

    Expected endpoint:
    POST {base_url}/embeddings

    Expected response path:
    response["data"][i]["embedding"]
    response["data"][i]["index"]
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BGE_API_BASE_URL,
        model_name: str = DEFAULT_BGE_EMBEDDING_MODEL,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)

    def embed_text(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        return vectors[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        response = self._client.post(
            f"{self.base_url}/embeddings",
            json={
                "model": self.model_name,
                "input": texts,
                "encoding_format": "float",
            },
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"BGE embedding request failed with status "
                f"{exc.response.status_code}: {exc.response.text}"
            ) from exc

        payload = response.json()
        return self._extract_embeddings(
            payload=payload,
            expected_count=len(texts),
        )

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _extract_embeddings(
        payload: dict[str, Any],
        expected_count: int,
    ) -> list[list[float]]:
        data = payload.get("data")

        if not isinstance(data, list):
            raise RuntimeError("BGE embedding response must contain a data list.")

        vectors_by_index: dict[int, list[float]] = {}

        for item in data:
            if not isinstance(item, dict):
                raise RuntimeError("Each embedding response item must be an object.")

            index = item.get("index")
            embedding = item.get("embedding")

            if not isinstance(index, int):
                raise RuntimeError("Embedding response item must contain integer index.")

            if not isinstance(embedding, list) or not embedding:
                raise RuntimeError("Embedding response item must contain non-empty embedding list.")

            vectors_by_index[index] = [float(value) for value in embedding]

        missing_indexes = [
            index for index in range(expected_count) if index not in vectors_by_index
        ]

        if missing_indexes:
            raise RuntimeError(f"Embedding response missing indexes: {missing_indexes}")

        return [vectors_by_index[index] for index in range(expected_count)]
