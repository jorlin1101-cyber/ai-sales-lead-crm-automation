import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TypedDict

from lead_cleaner.rag.schemas import KnowledgeChunk, RetrievedChunk


class _ScoredChunk(TypedDict):
    chunk: KnowledgeChunk
    score: float


LATIN_NUMBER_PATTERN = re.compile(r"[a-zA-Z0-9]+")
CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")


FIELD_WEIGHTS = {
    "source_title": 3,
    "section": 3,
    "doc_type": 2,
    "region": 2,
    "product_name": 2,
    "source_path": 1,
    "text": 1,
}


QUERY_TOKEN_EXPANSIONS = {
    "川西": ["western", "sichuan"],
    "西藏": ["tibet"],
    "云南": ["yunnan"],
    "私人": ["private"],
    "定制": ["custom", "private"],
    "报价": ["quotation", "pricing"],
    "价格": ["pricing", "quotation"],
    "付款": ["payment"],
    "支付": ["payment"],
    "预订": ["booking"],
    "许可证": ["permit"],
    "入藏函": ["permit", "tibet"],
    "酒店": ["hotel"],
    "车辆": ["vehicle"],
    "导游": ["guide"],
    "家庭": ["family"],
    "cost": ["pricing", "price", "quotation"],
    "costs": ["pricing", "price", "quotation"],
    "quote": ["quotation", "pricing"],
    "quoted": ["quotation", "pricing"],
    "budget": ["pricing", "price", "quotation"],
    "custom": ["private", "custom", "pricing", "quotation"],
    "customized": ["private", "custom", "pricing", "quotation"],
    "customised": ["private", "custom", "pricing", "quotation"],
    "deposit": ["payment"],
    "balance": ["payment"],
    "permit": ["permit", "faq", "payment"],
    "foreign": ["permit", "faq"],
    "families": ["family", "children", "suitable", "experiences", "overview"],
    "children": ["family", "children", "suitable", "experiences", "overview"],
    "child": ["family", "children", "suitable", "experiences", "overview"],
    "kids": ["family", "children", "suitable", "experiences", "overview"],
    "experience": ["experiences", "suitable", "product"],
    "experiences": ["experiences", "suitable", "product"],
    "arrange": ["private", "custom", "product"],
    "arranged": ["private", "custom", "product"],
}


def _cjk_ngrams(text: str, min_n: int = 1, max_n: int = 2) -> list[str]:
    chars = [char for char in text if "\u4e00" <= char <= "\u9fff"]
    tokens: list[str] = []

    for n in range(min_n, max_n + 1):
        if len(chars) < n:
            continue

        for index in range(0, len(chars) - n + 1):
            tokens.append("".join(chars[index : index + n]))

    return tokens


def tokenize(text: str) -> list[str]:
    if not text:
        return []

    tokens: list[str] = []

    tokens.extend(token.lower() for token in LATIN_NUMBER_PATTERN.findall(text))

    for cjk_segment in CJK_PATTERN.findall(text):
        tokens.extend(_cjk_ngrams(cjk_segment))

    return tokens


def _extend_weighted_tokens(
    tokens: list[str],
    field_value: str | None,
    weight: int,
) -> None:
    if not field_value:
        return

    if weight <= 0:
        return

    field_tokens = tokenize(field_value)
    tokens.extend(field_tokens * weight)


def tokenize_chunk_for_bm25(chunk: KnowledgeChunk) -> list[str]:
    tokens: list[str] = []

    _extend_weighted_tokens(
        tokens=tokens,
        field_value=chunk.source_title,
        weight=FIELD_WEIGHTS["source_title"],
    )
    _extend_weighted_tokens(
        tokens=tokens,
        field_value=chunk.section,
        weight=FIELD_WEIGHTS["section"],
    )
    _extend_weighted_tokens(
        tokens=tokens,
        field_value=chunk.doc_type,
        weight=FIELD_WEIGHTS["doc_type"],
    )
    _extend_weighted_tokens(
        tokens=tokens,
        field_value=chunk.region,
        weight=FIELD_WEIGHTS["region"],
    )
    _extend_weighted_tokens(
        tokens=tokens,
        field_value=chunk.product_name,
        weight=FIELD_WEIGHTS["product_name"],
    )
    _extend_weighted_tokens(
        tokens=tokens,
        field_value=chunk.source_path,
        weight=FIELD_WEIGHTS["source_path"],
    )
    _extend_weighted_tokens(
        tokens=tokens,
        field_value=chunk.text,
        weight=FIELD_WEIGHTS["text"],
    )

    return tokens


@dataclass
class BM25Index:
    chunks: list[KnowledgeChunk]
    tokenized_chunks: list[list[str]]
    term_frequencies: list[Counter[str]]
    document_frequencies: dict[str, int]
    idf: dict[str, float]
    document_lengths: list[int]
    average_document_length: float
    inverted_index: dict[str, set[int]] = field(default_factory=dict)
    k1: float = 1.2
    b: float = 0.75


def build_bm25_index(chunks: list[KnowledgeChunk]) -> BM25Index:
    tokenized_chunks = [tokenize_chunk_for_bm25(chunk) for chunk in chunks]

    term_frequencies = [Counter(tokens) for tokens in tokenized_chunks]

    document_lengths = [len(tokens) for tokens in tokenized_chunks]

    average_document_length = (
        sum(document_lengths) / len(document_lengths) if document_lengths else 0.0
    )

    document_frequencies: dict[str, int] = {}
    inverted_index: dict[str, set[int]] = {}

    for chunk_position, tokens in enumerate(tokenized_chunks):
        unique_tokens = set(tokens)

        for token in unique_tokens:
            document_frequencies[token] = document_frequencies.get(token, 0) + 1

            if token not in inverted_index:
                inverted_index[token] = set()

            inverted_index[token].add(chunk_position)

    total_documents = len(chunks)
    idf: dict[str, float] = {}

    for token, document_frequency in document_frequencies.items():
        idf[token] = math.log(
            1 + ((total_documents - document_frequency + 0.5) / (document_frequency + 0.5))
        )

    return BM25Index(
        chunks=chunks,
        tokenized_chunks=tokenized_chunks,
        term_frequencies=term_frequencies,
        document_frequencies=document_frequencies,
        idf=idf,
        document_lengths=document_lengths,
        average_document_length=average_document_length,
        inverted_index=inverted_index,
    )


def score_chunk(
    query_tokens: list[str],
    index: BM25Index,
    chunk_position: int,
) -> float:
    if not query_tokens:
        return 0.0

    if index.average_document_length == 0:
        return 0.0

    score = 0.0
    term_frequency = index.term_frequencies[chunk_position]
    document_length = index.document_lengths[chunk_position]

    for token in query_tokens:
        if token not in term_frequency:
            continue

        token_frequency = term_frequency[token]
        token_idf = index.idf.get(token, 0.0)

        numerator = token_frequency * (index.k1 + 1)
        denominator = token_frequency + index.k1 * (
            1 - index.b + index.b * document_length / index.average_document_length
        )

        score += token_idf * numerator / denominator

    return score


def _get_candidate_chunk_positions(
    query_tokens: list[str],
    index: BM25Index,
) -> set[int]:
    candidate_positions: set[int] = set()

    for token in query_tokens:
        candidate_positions.update(index.inverted_index.get(token, set()))

    return candidate_positions


def knowledge_chunk_to_retrieved_chunk(
    chunk: KnowledgeChunk,
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
        retrieval_source="bm25",
    )


def retrieve_bm25(
    query: str,
    index: BM25Index,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")

    query_tokens = expand_query_tokens(tokenize(query))

    if not query_tokens:
        return []

    candidate_positions = _get_candidate_chunk_positions(
        query_tokens=query_tokens,
        index=index,
    )

    scored_chunks: list[_ScoredChunk] = []

    for chunk_position in candidate_positions:
        chunk = index.chunks[chunk_position]
        score = score_chunk(
            query_tokens=query_tokens,
            index=index,
            chunk_position=chunk_position,
        )

        if score > 0:
            scored_chunks.append(
                {
                    "chunk": chunk,
                    "score": score,
                }
            )

    scored_chunks.sort(
        key=lambda item: (
            -item["score"],
            item["chunk"].chunk_id,
        )
    )

    top_results = scored_chunks[:top_k]

    return [
        knowledge_chunk_to_retrieved_chunk(
            chunk=item["chunk"],
            score=item["score"],
            rank=rank,
        )
        for rank, item in enumerate(top_results, start=1)
    ]


def expand_query_tokens(query_tokens: list[str]) -> list[str]:
    expanded_tokens: list[str] = []

    for token in query_tokens:
        expanded_tokens.append(token)
        expanded_tokens.extend(QUERY_TOKEN_EXPANSIONS.get(token, []))

    return list(dict.fromkeys(expanded_tokens))
