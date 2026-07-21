from lead_cleaner.rag.retriever import RagRetrievalOutcome, RagRetriever
from lead_cleaner.rag.rrf_fusion import DEFAULT_RRF_K, fuse_retrieved_chunks
from lead_cleaner.rag.schemas import RetrievedChunk


DEFAULT_PRIMARY_QUERY_WEIGHT = 2


def fuse_query_result_lists(
    result_lists: list[list[RetrievedChunk]],
    *,
    top_k: int = 3,
    rrf_k: int = DEFAULT_RRF_K,
    primary_query_weight: int = DEFAULT_PRIMARY_QUERY_WEIGHT,
) -> list[RetrievedChunk]:
    """Fuse query rankings while keeping the sanitized original query primary."""

    if not result_lists:
        return []
    if primary_query_weight < 1:
        raise ValueError("primary_query_weight must be at least 1.")

    weighted_lists = [result_lists[0]] * primary_query_weight + result_lists[1:]
    return fuse_retrieved_chunks(
        result_lists=weighted_lists,
        top_k=top_k,
        k=rrf_k,
    )


def retrieve_queries_with_rrf(
    retriever: RagRetriever,
    queries: list[str],
    *,
    top_k: int = 3,
    rrf_k: int = DEFAULT_RRF_K,
) -> RagRetrievalOutcome:
    """Retrieve distinct queries and fuse their rankings without changing the backend label."""

    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")

    unique_queries = list(dict.fromkeys(query.strip() for query in queries if query.strip()))
    if not unique_queries:
        raise ValueError("At least one non-empty retrieval query is required.")

    outcomes: list[RagRetrievalOutcome] = []
    for query in unique_queries:
        outcome = retriever.retrieve(query)
        if outcome.retrieval_method in {"disabled", "unavailable", "skipped"}:
            return outcome
        outcomes.append(outcome)

    retrieval_methods = {outcome.retrieval_method for outcome in outcomes}
    if len(retrieval_methods) != 1:
        raise ValueError("All query results must use the same retrieval method.")

    if len(outcomes) == 1:
        return outcomes[0]

    fused_chunks = fuse_query_result_lists(
        [outcome.chunks for outcome in outcomes],
        top_k=top_k,
        rrf_k=rrf_k,
    )
    return RagRetrievalOutcome(
        chunks=fused_chunks,
        retrieval_method=outcomes[0].retrieval_method,
    )
