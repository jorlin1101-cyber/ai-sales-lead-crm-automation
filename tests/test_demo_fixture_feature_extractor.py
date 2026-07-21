import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lead_cleaner.config import AppMode
from lead_cleaner.schemas.lead import CleanedLead
from lead_cleaner.services.demo_fixture_feature_extractor import (
    DemoFixtureFeatureExtractor,
)
from lead_cleaner.services.feature_extractor import FeatureExtractor


FIXTURE_PATH = Path("data/demo/lead_feature_fixtures.json")


def make_cleaned_lead(
    *,
    external_lead_id: str | None,
    message: str = "We need a private Chengdu tour.",
    company_name: str = "",
) -> CleanedLead:
    return CleanedLead(
        lead_id="lead-demo-test",
        external_lead_id=external_lead_id,
        name="Demo Lead",
        email="demo@example.com",
        company_name=company_name,
        message=message,
        source="Demo",
    )


def test_fixture_hit_returns_demo_features():
    extractor = DemoFixtureFeatureExtractor(FIXTURE_PATH)
    lead = make_cleaned_lead(
        external_lead_id="sample-lead-001",
        company_name="Example Company",
    )

    outcome = extractor.extract(lead)

    assert outcome.execution_mode == AppMode.DEMO
    assert outcome.analysis_method == "demo_fixture"
    assert outcome.fallback_reason is None
    assert outcome.provider is None
    assert outcome.features.customer_kind == "individual"
    assert outcome.features.destinations == ["Chengdu"]
    assert outcome.features.company_name_present is True
    assert outcome.features.cleaned_message_length == len(lead.message)


def test_fixture_miss_uses_rule_fallback():
    extractor = DemoFixtureFeatureExtractor(FIXTURE_PATH)
    lead = make_cleaned_lead(
        external_lead_id="not-in-fixtures",
        message="We are a travel agency requesting a quotation.",
    )

    outcome = extractor.extract(lead)

    assert outcome.execution_mode == AppMode.DEMO
    assert outcome.analysis_method == "rule_features"
    assert outcome.fallback_reason == "demo_fixture_not_found"
    assert outcome.features.customer_kind == "agency"


def test_missing_external_lead_id_uses_rule_fallback():
    extractor = DemoFixtureFeatureExtractor(FIXTURE_PATH)
    lead = make_cleaned_lead(external_lead_id=None)

    outcome = extractor.extract(lead)

    assert outcome.analysis_method == "rule_features"
    assert outcome.fallback_reason == "demo_fixture_not_found"


def test_fixture_rejects_server_owned_feature(tmp_path: Path):
    invalid_path = tmp_path / "invalid-fixtures.json"
    invalid_path.write_text(
        json.dumps(
            [
                {
                    "external_lead_id": "demo-invalid",
                    "features": {
                        "customer_kind": "agency",
                        "company_name_present": True,
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        DemoFixtureFeatureExtractor(invalid_path)


def test_demo_extractor_matches_common_protocol():
    extractor = DemoFixtureFeatureExtractor(FIXTURE_PATH)

    assert isinstance(extractor, FeatureExtractor)
