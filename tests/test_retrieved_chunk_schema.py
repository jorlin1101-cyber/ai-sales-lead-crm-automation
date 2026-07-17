import pytest
from pydantic import ValidationError

from lead_cleaner.rag.schemas import RetrievedChunk


def make_retrieved_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="chunk_1",
        source_type="notion_page",
        notion_page_id="page_1",
        source_title="Private Tour Pricing Rules",
        source_path="AI Sales Knowledge Base/Pricing/Private Tour Pricing Rules",
        doc_type="pricing",
        region="general",
        product_name=None,
        section="Group Size",
        text=(
            "# Private Tour Pricing Rules\n"
            "## Group Size\n"
            "- 15–25 travelers may require a coach."
        ),
        score=12.5,
        rank=1,
        retrieval_source="bm25",
    )


def model_to_dict(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")

    return model.dict()


def test_retrieved_chunk_accepts_valid_data() -> None:
    retrieved_chunk = make_retrieved_chunk()

    assert retrieved_chunk.chunk_id == "chunk_1"
    assert retrieved_chunk.source_type == "notion_page"
    assert retrieved_chunk.doc_type == "pricing"
    assert retrieved_chunk.region == "general"
    assert retrieved_chunk.section == "Group Size"
    assert retrieved_chunk.score == 12.5
    assert retrieved_chunk.rank == 1
    assert retrieved_chunk.retrieval_source == "bm25"


def test_retrieved_chunk_rejects_empty_text() -> None:
    data = model_to_dict(make_retrieved_chunk())
    data["text"] = ""

    with pytest.raises(ValidationError):
        RetrievedChunk(**data)


def test_retrieved_chunk_rejects_rank_zero() -> None:
    data = model_to_dict(make_retrieved_chunk())
    data["rank"] = 0

    with pytest.raises(ValidationError):
        RetrievedChunk(**data)


def test_retrieved_chunk_rejects_invalid_retrieval_source() -> None:
    data = model_to_dict(make_retrieved_chunk())
    data["retrieval_source"] = "keyword"

    with pytest.raises(ValidationError):
        RetrievedChunk(**data)


def test_retrieved_chunk_rejects_invalid_doc_type() -> None:
    data = model_to_dict(make_retrieved_chunk())
    data["doc_type"] = "company"

    with pytest.raises(ValidationError):
        RetrievedChunk(**data)
