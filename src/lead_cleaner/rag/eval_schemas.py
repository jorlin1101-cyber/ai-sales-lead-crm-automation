from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lead_cleaner.schemas.policy import ShortCode


RelevanceGrade = Literal[0, 1, 2, 3]
QueryLanguage = Literal["en", "zh", "mixed"]
QueryType = Literal["single_intent", "fuzzy", "multi_intent", "cross_lingual"]


class RetrievalFacet(BaseModel):
    """A distinct information need that a retrieval result should cover."""

    model_config = ConfigDict(extra="forbid")

    facet_id: ShortCode
    description: str = Field(min_length=1, max_length=300)


class RelevanceJudgment(BaseModel):
    """A graded relevance label for one concrete source-title/section pair."""

    model_config = ConfigDict(extra="forbid")

    source_title: str = Field(min_length=1)
    section: str = Field(min_length=1)
    relevance_grade: RelevanceGrade
    covers_facets: list[ShortCode] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_unique_facets(self) -> Self:
        if len(self.covers_facets) != len(set(self.covers_facets)):
            raise ValueError("covers_facets must not contain duplicates")
        if self.relevance_grade == 0 and self.covers_facets:
            raise ValueError("grade-0 judgments must not cover any facets")
        if self.relevance_grade > 0 and not self.covers_facets:
            raise ValueError("grade-1, grade-2, and grade-3 judgments must cover a facet")
        return self


class RagEvalCase(BaseModel):
    """One frozen retrieval query with paired, graded relevance judgments."""

    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    language: QueryLanguage
    query_type: QueryType
    facets: list[RetrievalFacet] = Field(min_length=1)
    judgments: list[RelevanceJudgment] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_label_consistency(self) -> Self:
        facet_ids = [facet.facet_id for facet in self.facets]
        if len(facet_ids) != len(set(facet_ids)):
            raise ValueError("facet_id values must be unique within an evaluation case")

        judgment_keys = [(judgment.source_title, judgment.section) for judgment in self.judgments]
        if len(judgment_keys) != len(set(judgment_keys)):
            raise ValueError(
                "source_title and section pairs must be unique within an evaluation case"
            )

        declared_facets = set(facet_ids)
        for judgment in self.judgments:
            unknown_facets = set(judgment.covers_facets) - declared_facets
            if unknown_facets:
                unknown = ", ".join(sorted(unknown_facets))
                raise ValueError(f"judgment references unknown facets: {unknown}")

        direct_judgments = [
            judgment for judgment in self.judgments if judgment.relevance_grade == 3
        ]
        if not direct_judgments:
            raise ValueError("each evaluation case must contain a grade-3 direct answer")

        directly_covered_facets = {
            facet_id for judgment in direct_judgments for facet_id in judgment.covers_facets
        }
        missing_direct_coverage = declared_facets - directly_covered_facets
        if missing_direct_coverage:
            missing = ", ".join(sorted(missing_direct_coverage))
            raise ValueError(
                f"every facet must be covered by at least one grade-3 judgment; missing: {missing}"
            )

        return self
