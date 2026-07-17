from dataclasses import dataclass

from lead_cleaner.rag.eval_schemas import RagEvalCase
from lead_cleaner.rag.schemas import RetrievedChunk


@dataclass(frozen=True)
class EvalMatchDetail:
    doc_type_hit: bool
    region_hit: bool
    source_title_hit: bool
    section_hit: bool

    @property
    def overall_match(self) -> bool:
        return (
            self.doc_type_hit
            and self.region_hit
            and self.source_title_hit
            and self.section_hit
        )


def evaluate_match_detail(
    result: RetrievedChunk,
    eval_case: RagEvalCase,
) -> EvalMatchDetail:
    return EvalMatchDetail(
        doc_type_hit=result.doc_type == eval_case.expected_doc_type,
        region_hit=result.region == eval_case.expected_region,
        source_title_hit=result.source_title in eval_case.expected_source_titles,
        section_hit=result.section in eval_case.expected_sections,
    )


def is_expected_match(result: RetrievedChunk, eval_case: RagEvalCase) -> bool:
    return evaluate_match_detail(
        result=result,
        eval_case=eval_case,
    ).overall_match


def has_expected_match(
    results: list[RetrievedChunk],
    eval_case: RagEvalCase,
    top_k: int,
) -> bool:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")

    return any(
        is_expected_match(result=result, eval_case=eval_case)
        for result in results[:top_k]
    )
