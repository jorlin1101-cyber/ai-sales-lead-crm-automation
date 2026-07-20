from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from lead_cleaner.config import AppMode
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.schemas.policy import ExtractedLeadFeatures
from lead_cleaner.services.feature_extractor import FeatureExtractionOutcome
from lead_cleaner.services.lead_feature_merger import (
    merge_extracted_features_with_server_facts,
)
from lead_cleaner.services.rule_feature_extractor import RuleFeatureExtractor


class DemoFeatureFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_lead_id: str = Field(min_length=1, max_length=100)
    features: ExtractedLeadFeatures


_fixture_list_adapter = TypeAdapter(list[DemoFeatureFixture])


class DemoFixtureFeatureExtractor:
    def __init__(self, fixture_path: str | Path) -> None:
        self._fixtures = self._load_fixtures(Path(fixture_path))
        self._rule_fallback = RuleFeatureExtractor(
            execution_mode=AppMode.DEMO,
            fallback_reason="demo_fixture_not_found",
        )

    @staticmethod
    def _load_fixtures(
        fixture_path: Path,
    ) -> dict[str, ExtractedLeadFeatures]:
        fixture_text = fixture_path.read_text(encoding="utf-8")
        fixture_items = _fixture_list_adapter.validate_json(fixture_text)

        fixtures: dict[str, ExtractedLeadFeatures] = {}

        for item in fixture_items:
            if item.external_lead_id in fixtures:
                raise ValueError(f"Duplicate demo external_lead_id: {item.external_lead_id}")

            fixtures[item.external_lead_id] = item.features

        return fixtures

    def extract(
        self,
        cleaned_lead: CleanedLead,
    ) -> FeatureExtractionOutcome:
        external_lead_id = (cleaned_lead.external_lead_id or "").strip()
        extracted_features = self._fixtures.get(external_lead_id)

        if extracted_features is None:
            return self._rule_fallback.extract(cleaned_lead)

        features = merge_extracted_features_with_server_facts(
            extracted_features,
            cleaned_lead,
        )

        return FeatureExtractionOutcome(
            features=features,
            execution_mode=AppMode.DEMO,
            analysis_method="demo_fixture",
        )
