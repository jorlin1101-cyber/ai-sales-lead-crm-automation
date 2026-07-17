from pydantic import BaseModel, Field


class RagEvalCase(BaseModel):
    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    expected_region: str = Field(min_length=1)
    expected_doc_type: str = Field(min_length=1)
    expected_source_titles: list[str] = Field(min_length=1)
    expected_sections: list[str] = Field(min_length=1)
