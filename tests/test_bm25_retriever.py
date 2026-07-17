import pytest

from lead_cleaner.rag.bm25_retriever import (
    build_bm25_index,
    retrieve_bm25,
    tokenize,
    tokenize_chunk_for_bm25,
    expand_query_tokens
)
from lead_cleaner.rag.schemas import KnowledgeChunk


def make_chunk(
    chunk_id: str,
    source_title: str,
    section: str,
    text: str,
    doc_type: str = "pricing",
    region: str = "general",
    product_name: str | None = None,
    source_path: str = "AI Sales Knowledge Base/Pricing/Private Tour Pricing Rules",
) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        source_type="notion_page",
        notion_page_id=f"page_{chunk_id}",
        source_title=source_title,
        source_path=source_path,
        doc_type=doc_type,
        region=region,
        product_name=product_name,
        section=section,
        chunk_index=0,
        chunk_strategy="heading_section",
        text=text,
        last_edited_time="2026-06-16T10:00:00Z",
    )


def test_tokenize_supports_english_numbers_and_chinese() -> None:
    tokens = tokenize("Western Sichuan 20 people 川西私人")

    assert "western" in tokens
    assert "sichuan" in tokens
    assert "20" in tokens
    assert "people" in tokens
    assert "川" in tokens
    assert "西" in tokens
    assert "川西" in tokens
    assert "私人" in tokens


def test_expand_query_tokens_adds_business_synonyms_for_chinese_query() -> None:
    query_tokens = tokenize("川西 私人 定制 报价")

    expanded_tokens = expand_query_tokens(query_tokens)

    assert "川西" in expanded_tokens
    assert "western" in expanded_tokens
    assert "sichuan" in expanded_tokens
    assert "私人" in expanded_tokens
    assert "private" in expanded_tokens
    assert "定制" in expanded_tokens
    assert "custom" in expanded_tokens
    assert "报价" in expanded_tokens
    assert "quotation" in expanded_tokens
    assert "pricing" in expanded_tokens


def test_tokenize_chunk_for_bm25_applies_section_field_weight() -> None:
    chunk = make_chunk(
        chunk_id="chunk_1",
        source_title="Pricing Rules",
        section="Group Size",
        text="This text does not repeat the section terms.",
        source_path="Knowledge/Pricing",
    )

    tokens = tokenize_chunk_for_bm25(chunk)

    assert tokens.count("group") == 3
    assert tokens.count("size") == 3


def test_build_bm25_index_creates_term_frequency_idf_and_inverted_index() -> None:
    chunks = [
        make_chunk(
            chunk_id="chunk_1",
            source_title="Private Tour Pricing Rules",
            section="Group Size",
            text="Group size affects private quotation.",
        ),
        make_chunk(
            chunk_id="chunk_2",
            source_title="Travel Permit and Payment FAQ",
            section="Payment",
            text="Payment and booking notes.",
            doc_type="faq",
        ),
    ]

    index = build_bm25_index(chunks)

    assert len(index.chunks) == 2
    assert len(index.tokenized_chunks) == 2
    assert len(index.term_frequencies) == 2
    assert len(index.document_lengths) == 2
    assert index.average_document_length > 0

    assert "quotation" in index.document_frequencies
    assert "quotation" in index.idf
    assert index.document_frequencies["quotation"] == 1
    assert index.inverted_index["quotation"] == {0}


def test_retrieve_bm25_returns_relevant_chunks_with_metadata() -> None:
    chunks = [
        make_chunk(
            chunk_id="chunk_pricing",
            source_title="Private Tour Pricing Rules",
            section="Group Size",
            text="A 20 people private quotation depends on group size and vehicle type.",
            doc_type="pricing",
            region="general",
            source_path="AI Sales Knowledge Base/Pricing/Private Tour Pricing Rules",
        ),
        make_chunk(
            chunk_id="chunk_payment",
            source_title="Travel Permit and Payment FAQ",
            section="Payment and Booking",
            text="Payment and booking steps for confirmed trips.",
            doc_type="faq",
            region="general",
            source_path="AI Sales Knowledge Base/FAQ/Travel Permit and Payment FAQ",
        ),
        make_chunk(
            chunk_id="chunk_tibet",
            source_title="Tibet Destination Overview",
            section="Travel Permit",
            text="Tibet permit requirements for cultural travel.",
            doc_type="destination",
            region="tibet",
            source_path="AI Sales Knowledge Base/Destinations/Tibet Destination Overview",
        ),
    ]

    index = build_bm25_index(chunks)

    results = retrieve_bm25(
        query="20 people private quotation",
        index=index,
        top_k=1,
    )

    assert len(results) == 1
    assert results[0].chunk_id == "chunk_pricing"
    assert results[0].source_title == "Private Tour Pricing Rules"
    assert results[0].doc_type == "pricing"
    assert results[0].section == "Group Size"
    assert results[0].rank == 1
    assert results[0].retrieval_source == "bm25"
    assert results[0].score > 0


def test_retrieve_bm25_supports_chinese_query_expansion() -> None:
    chunks = [
        make_chunk(
            chunk_id="chunk_western_sichuan",
            source_title="Western Sichuan Private Tour",
            section="Pricing Notes",
            text="Private custom tour quotation for western Sichuan depends on group size.",
            doc_type="product",
            region="western_sichuan",
            product_name="Western Sichuan Private Tour",
            source_path="AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour",
        ),
        make_chunk(
            chunk_id="chunk_yunnan",
            source_title="Yunnan Family Tour",
            section="Suitable For",
            text="Family travel in Yunnan with cultural experiences.",
            doc_type="product",
            region="yunnan",
            product_name="Yunnan Family Tour",
            source_path="AI Sales Knowledge Base/Products/Yunnan/Yunnan Family Tour",
        ),
    ]

    index = build_bm25_index(chunks)

    results = retrieve_bm25(
        query="川西 私人 定制 报价",
        index=index,
        top_k=1,
    )

    assert len(results) == 1
    assert results[0].chunk_id == "chunk_western_sichuan"
    assert results[0].source_title == "Western Sichuan Private Tour"
    assert results[0].region == "western_sichuan"
    assert results[0].retrieval_source == "bm25"
    assert results[0].score > 0


def test_retrieve_bm25_respects_top_k() -> None:
    chunks = [
        make_chunk(
            chunk_id="chunk_1",
            source_title="Private Tour Pricing Rules",
            section="Pricing Variables",
            text="Private quotation depends on hotel level.",
        ),
        make_chunk(
            chunk_id="chunk_2",
            source_title="Private Tour Pricing Rules",
            section="Vehicle Type",
            text="Private quotation depends on vehicle type.",
        ),
        make_chunk(
            chunk_id="chunk_3",
            source_title="Private Tour Pricing Rules",
            section="Guide Requirement",
            text="Private quotation depends on guide requirement.",
        ),
    ]

    index = build_bm25_index(chunks)

    results = retrieve_bm25(
        query="private quotation",
        index=index,
        top_k=2,
    )

    assert len(results) == 2
    assert results[0].rank == 1
    assert results[1].rank == 2


def test_retrieve_bm25_returns_empty_list_for_empty_query() -> None:
    chunk = make_chunk(
        chunk_id="chunk_1",
        source_title="Private Tour Pricing Rules",
        section="Group Size",
        text="Group size affects private quotation.",
    )

    index = build_bm25_index([chunk])

    assert retrieve_bm25(query="!!!", index=index) == []


def test_retrieve_bm25_raises_when_top_k_is_not_positive() -> None:
    chunk = make_chunk(
        chunk_id="chunk_1",
        source_title="Private Tour Pricing Rules",
        section="Group Size",
        text="Group size affects private quotation.",
    )

    index = build_bm25_index([chunk])

    with pytest.raises(ValueError, match="top_k must be greater than 0"):
        retrieve_bm25(query="quotation", index=index, top_k=0)
