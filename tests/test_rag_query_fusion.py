from lead_cleaner.rag.query_fusion import retrieve_queries_with_rrf
from lead_cleaner.rag.retriever import RagRetrievalOutcome
from lead_cleaner.rag.schemas import RetrievedChunk


class StubRetriever:
    def __init__(self, outcomes: dict[str, RagRetrievalOutcome]) -> None:
        self.outcomes = outcomes
        self.queries: list[str] = []

    def retrieve(self, query: str) -> RagRetrievalOutcome:
        self.queries.append(query)
        return self.outcomes[query]


def make_chunk(chunk_id: str, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_type="notion_page",
        notion_page_id=f"page-{chunk_id}",
        source_title=f"Source {chunk_id}",
        source_path=f"Knowledge/{chunk_id}",
        doc_type="faq",
        region="general",
        product_name=None,
        section="FAQ",
        text="Knowledge text",
        score=1.0,
        rank=rank,
        retrieval_source="fusion",
    )


def test_two_query_rankings_are_fused_and_duplicate_chunks_gain_weight() -> None:
    retriever = StubRetriever(
        {
            "original": RagRetrievalOutcome(
                chunks=[make_chunk("a", 1), make_chunk("shared", 2)],
                retrieval_method="keyword_rrf",
            ),
            "intent": RagRetrievalOutcome(
                chunks=[make_chunk("b", 1), make_chunk("shared", 2)],
                retrieval_method="keyword_rrf",
            ),
        }
    )

    outcome = retrieve_queries_with_rrf(retriever, ["original", "intent"])

    assert retriever.queries == ["original", "intent"]
    assert outcome.retrieval_method == "keyword_rrf"
    assert [chunk.chunk_id for chunk in outcome.chunks] == ["shared", "a", "b"]
    assert [chunk.rank for chunk in outcome.chunks] == [1, 2, 3]


def test_duplicate_queries_are_only_retrieved_once() -> None:
    outcome = RagRetrievalOutcome(
        chunks=[make_chunk("a", 1)],
        retrieval_method="keyword_rrf",
    )
    retriever = StubRetriever({"same query": outcome})

    actual = retrieve_queries_with_rrf(retriever, [" same query ", "same query"])

    assert actual is outcome
    assert retriever.queries == ["same query"]


def test_original_query_has_more_weight_than_a_conflicting_expansion() -> None:
    retriever = StubRetriever(
        {
            "original": RagRetrievalOutcome(
                chunks=[make_chunk("original-result", 1)],
                retrieval_method="keyword_rrf",
            ),
            "intent": RagRetrievalOutcome(
                chunks=[make_chunk("expanded-result", 1)],
                retrieval_method="keyword_rrf",
            ),
        }
    )

    outcome = retrieve_queries_with_rrf(retriever, ["original", "intent"])

    assert [chunk.chunk_id for chunk in outcome.chunks] == [
        "original-result",
        "expanded-result",
    ]


def test_unavailable_query_returns_truthful_failure_without_partial_sources() -> None:
    retriever = StubRetriever(
        {
            "original": RagRetrievalOutcome(
                chunks=[make_chunk("a", 1)],
                retrieval_method="keyword_rrf",
            ),
            "intent": RagRetrievalOutcome(
                retrieval_method="unavailable",
                failure_reason="retrieval_failure",
            ),
        }
    )

    outcome = retrieve_queries_with_rrf(retriever, ["original", "intent"])

    assert outcome.retrieval_method == "unavailable"
    assert outcome.failure_reason == "retrieval_failure"
    assert outcome.chunks == []
