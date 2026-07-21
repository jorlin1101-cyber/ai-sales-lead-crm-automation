import json
from pathlib import Path

import pytest

from lead_cleaner.config import RagBackend, Settings
from lead_cleaner.rag import retriever_factory
from lead_cleaner.rag.retriever import (
    DisabledRagRetriever,
    HybridRagRetriever,
    RagUnavailableError,
    UnavailableRagRetriever,
)


def make_chunk() -> dict[str, object]:
    return {
        "chunk_id": "chunk-1",
        "source_type": "notion_page",
        "notion_page_id": "private-page-id",
        "source_title": "Private Tour Pricing Rules",
        "source_path": "Knowledge/Pricing",
        "doc_type": "pricing",
        "region": "general",
        "product_name": None,
        "section": "Pricing Variables",
        "chunk_index": 0,
        "chunk_strategy": "heading_section",
        "text": "Private tour pricing depends on group size.",
        "last_edited_time": "2026-07-01T00:00:00Z",
    }


def write_chunks(path: Path) -> None:
    path.write_text(json.dumps([make_chunk()]), encoding="utf-8")


class FakeBgeProvider:
    model_name = "fake-bge"
    instances: list["FakeBgeProvider"] = []

    def __init__(self, *, base_url: str, model_name: str, timeout: float) -> None:
        self.base_url = base_url
        self.model_name = model_name
        self.timeout = timeout
        self.close_calls = 0
        self.instances.append(self)

    def embed_text(self, text: str) -> list[float]:
        return [1.0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] for _ in texts]

    def close(self) -> None:
        self.close_calls += 1


def test_disabled_factory_does_not_read_missing_snapshot(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        rag_backend=RagBackend.DISABLED,
        knowledge_chunks_path=tmp_path / "missing.json",
    )

    retriever = retriever_factory.create_rag_retriever(settings)

    assert isinstance(retriever, DisabledRagRetriever)


def test_keyword_factory_builds_offline_hybrid_retriever(tmp_path) -> None:
    chunks_path = tmp_path / "chunks.json"
    write_chunks(chunks_path)
    settings = Settings(
        _env_file=None,
        rag_backend=RagBackend.KEYWORD_RRF,
        knowledge_chunks_path=chunks_path,
    )

    retriever = retriever_factory.create_rag_retriever(settings)
    outcome = retriever.retrieve("private tour pricing group size")

    assert isinstance(retriever, HybridRagRetriever)
    assert outcome.retrieval_method == "keyword_rrf"
    assert [chunk.chunk_id for chunk in outcome.chunks] == ["chunk-1"]


def test_optional_startup_failure_returns_unavailable_retriever(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        rag_backend=RagBackend.KEYWORD_RRF,
        rag_required=False,
        knowledge_chunks_path=tmp_path / "missing.json",
    )

    retriever = retriever_factory.create_rag_retriever(settings)

    assert isinstance(retriever, UnavailableRagRetriever)
    assert retriever.retrieve("query").retrieval_method == "unavailable"


def test_required_startup_failure_raises(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        rag_backend=RagBackend.KEYWORD_RRF,
        rag_required=True,
        knowledge_chunks_path=tmp_path / "missing.json",
    )

    with pytest.raises(RagUnavailableError, match="failed to start"):
        retriever_factory.create_rag_retriever(settings)


def test_bge_factory_uses_port_8001_configuration(monkeypatch, tmp_path) -> None:
    chunks_path = tmp_path / "chunks.json"
    write_chunks(chunks_path)
    FakeBgeProvider.instances = []
    monkeypatch.setattr(
        retriever_factory,
        "BgeM3EmbeddingProvider",
        FakeBgeProvider,
    )
    settings = Settings(
        _env_file=None,
        allow_network=True,
        rag_backend=RagBackend.BGE_RRF,
        knowledge_chunks_path=chunks_path,
    )

    retriever = retriever_factory.create_rag_retriever(settings)

    assert isinstance(retriever, HybridRagRetriever)
    assert FakeBgeProvider.instances[0].base_url == "http://127.0.0.1:8001/v1"
    assert retriever.retrieve("pricing").retrieval_method == "bge_rrf"
    retriever.close()
    assert FakeBgeProvider.instances[0].close_calls == 1
