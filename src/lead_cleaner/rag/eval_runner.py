import math
from collections.abc import Sequence
from dataclasses import dataclass

from lead_cleaner.rag.eval_schemas import RagEvalCase, RelevanceJudgment
from lead_cleaner.rag.schemas import KnowledgeChunk, RetrievedChunk


DIRECT_RELEVANCE_GRADE = 3
USEFUL_RELEVANCE_GRADE = 2


@dataclass(frozen=True)
class EvalMatchDetail:
    relevance_grade: int
    judged: bool
    relevant_match: bool
    direct_match: bool
    source_match: bool
    covers_facets: tuple[str, ...]

    @property
    def overall_match(self) -> bool:
        """Backward-compatible name for a grade-3 direct match."""

        return self.direct_match


def _judgment_key(source_title: str, section: str) -> tuple[str, str]:
    return source_title, section


def _judgments_by_key(
    eval_case: RagEvalCase,
) -> dict[tuple[str, str], RelevanceJudgment]:
    return {
        _judgment_key(judgment.source_title, judgment.section): judgment
        for judgment in eval_case.judgments
    }


def get_relevance_judgment(
    result: RetrievedChunk,
    eval_case: RagEvalCase,
) -> RelevanceJudgment | None:
    return _judgments_by_key(eval_case).get(_judgment_key(result.source_title, result.section))


def evaluate_match_detail(
    result: RetrievedChunk,
    eval_case: RagEvalCase,
) -> EvalMatchDetail:
    judgment = get_relevance_judgment(result, eval_case)
    relevance_grade = judgment.relevance_grade if judgment else 0
    relevant_source_titles = {
        item.source_title
        for item in eval_case.judgments
        if item.relevance_grade >= USEFUL_RELEVANCE_GRADE
    }
    return EvalMatchDetail(
        relevance_grade=relevance_grade,
        judged=judgment is not None,
        relevant_match=relevance_grade >= USEFUL_RELEVANCE_GRADE,
        direct_match=relevance_grade == DIRECT_RELEVANCE_GRADE,
        source_match=result.source_title in relevant_source_titles,
        covers_facets=tuple(judgment.covers_facets) if judgment else (),
    )


def is_expected_match(result: RetrievedChunk, eval_case: RagEvalCase) -> bool:
    """Return whether a result is a grade-3 direct answer."""

    return evaluate_match_detail(result=result, eval_case=eval_case).direct_match


def has_expected_match(
    results: list[RetrievedChunk],
    eval_case: RagEvalCase,
    top_k: int,
) -> bool:
    """Backward-compatible direct-answer hit check."""

    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")

    return any(is_expected_match(result=result, eval_case=eval_case) for result in results[:top_k])


def has_expected_source(
    results: list[RetrievedChunk],
    eval_case: RagEvalCase,
    top_k: int,
) -> bool:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")
    return any(evaluate_match_detail(result, eval_case).source_match for result in results[:top_k])


def reciprocal_rank(results: list[RetrievedChunk], eval_case: RagEvalCase) -> float:
    for rank, result in enumerate(results, start=1):
        if is_expected_match(result, eval_case):
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    results: list[RetrievedChunk],
    eval_case: RagEvalCase,
    top_k: int,
) -> float:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")

    retrieved_grades = [
        evaluate_match_detail(result, eval_case).relevance_grade for result in results[:top_k]
    ]
    ideal_grades = sorted(
        (judgment.relevance_grade for judgment in eval_case.judgments),
        reverse=True,
    )[:top_k]

    def discounted_gain(grades: Sequence[int]) -> float:
        return sum(
            ((2**grade) - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1)
        )

    ideal_gain = discounted_gain(ideal_grades)
    if ideal_gain == 0:
        return 0.0
    return discounted_gain(retrieved_grades) / ideal_gain


def facet_recall_at_k(
    results: list[RetrievedChunk],
    eval_case: RagEvalCase,
    top_k: int,
) -> float:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")

    required_facets = {facet.facet_id for facet in eval_case.facets}
    covered_facets = {
        facet_id
        for result in results[:top_k]
        for detail in [evaluate_match_detail(result, eval_case)]
        if detail.direct_match
        for facet_id in detail.covers_facets
    }
    return len(covered_facets) / len(required_facets)


def unjudged_rate_at_k(
    results: list[RetrievedChunk],
    eval_case: RagEvalCase,
    top_k: int,
) -> float:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")
    window = results[:top_k]
    if not window:
        return 0.0
    unjudged_count = sum(not evaluate_match_detail(result, eval_case).judged for result in window)
    return unjudged_count / len(window)


def validate_eval_cases_against_chunks(
    eval_cases: list[RagEvalCase],
    chunks: list[KnowledgeChunk],
) -> None:
    available_keys = {_judgment_key(chunk.source_title, chunk.section) for chunk in chunks}
    errors: list[str] = []
    for eval_case in eval_cases:
        for judgment in eval_case.judgments:
            key = _judgment_key(judgment.source_title, judgment.section)
            if key not in available_keys:
                errors.append(
                    f"{eval_case.query_id}: missing knowledge chunk "
                    f"{judgment.source_title!r} / {judgment.section!r}"
                )
    if errors:
        raise ValueError("Invalid RAG relevance judgments:\n" + "\n".join(errors))
