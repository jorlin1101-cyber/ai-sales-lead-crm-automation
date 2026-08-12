import pytest

from scripts.demo_cli import (
    SCENARIOS,
    SCENARIO_PAYLOADS,
    build_parser,
    list_scenarios,
    process_scenario,
    run_rag_query,
)


EXPECTED_SCENARIO_NAMES = [
    "high",
    "medium",
    "low",
    "invalid",
    "injection",
    "spam",
    "model-failure",
]


def test_list_command_can_be_parsed() -> None:
    args = build_parser().parse_args(["list"])

    assert args.command == "list"


def test_demo_scenarios_cover_required_cases() -> None:
    scenario_names = [scenario.name for scenario in SCENARIOS]

    assert scenario_names == EXPECTED_SCENARIO_NAMES
    assert len(scenario_names) == len(set(scenario_names))


def test_list_scenarios_prints_every_scenario(capsys) -> None:
    list_scenarios()

    output = capsys.readouterr().out

    assert "Available demo scenarios:" in output

    for scenario in SCENARIOS:
        assert f"- {scenario.name}: {scenario.description}" in output


def test_process_command_accepts_known_scenario() -> None:
    args = build_parser().parse_args(["process", "--scenario", "high"])

    assert args.command == "process"
    assert args.scenario == "high"


def test_every_scenario_has_one_complete_payload() -> None:
    scenario_names = {scenario.name for scenario in SCENARIOS}

    assert set(SCENARIO_PAYLOADS) == scenario_names

    required_fields = {
        "external_lead_id",
        "name",
        "email",
        "company_name",
        "message",
        "source",
    }

    external_lead_ids = []

    for payload in SCENARIO_PAYLOADS.values():
        assert set(payload) == required_fields
        external_lead_ids.append(payload["external_lead_id"])

    assert len(external_lead_ids) == len(set(external_lead_ids))


def test_process_high_scenario_returns_stable_decision() -> None:
    result = process_scenario("high")

    assert result.validation_result.is_valid is True
    assert result.analysis_result is not None
    assert result.analysis_result.decision.lead_score == 100
    assert result.analysis_result.decision.intent_level == "High"
    assert result.analysis_result.decision.disposition == "qualified"


def test_model_failure_uses_rule_fallback() -> None:
    result = process_scenario("model-failure")

    assert result.validation_result.is_valid is True
    assert result.analysis_result is not None

    metadata = result.analysis_result.metadata

    assert metadata.execution_mode == "live"
    assert metadata.analysis_method == "rule_features"
    assert metadata.fallback_reason == "timeout"


def test_process_spam_scenario_uses_spam_override() -> None:
    result = process_scenario("spam")

    assert result.validation_result.is_valid is True
    assert result.analysis_result is not None

    analysis = result.analysis_result

    assert analysis.features.contains_spam_or_promotion is True
    assert analysis.decision.lead_score == 0
    assert analysis.decision.intent_level == "Low"
    assert analysis.decision.disposition == "spam"
    assert analysis.metadata.retrieval_method == "skipped"
    assert result.sources == []


def test_rag_command_accepts_query() -> None:
    args = build_parser().parse_args(["rag", "--query", "Tibet permit payment"])

    assert args.command == "rag"
    assert args.query == "Tibet permit payment"


def test_rag_query_uses_offline_keyword_retrieval() -> None:
    outcome = run_rag_query("Tibet permit payment")

    assert outcome.retrieval_method == "keyword_rrf"
    assert 1 <= len(outcome.chunks) <= 3
    assert [chunk.rank for chunk in outcome.chunks] == list(range(1, len(outcome.chunks) + 1))
    assert all(chunk.retrieval_source == "fusion" for chunk in outcome.chunks)


@pytest.mark.parametrize(
    ("scenario_name", "expected_valid"),
    [
        ("high", True),
        ("medium", True),
        ("low", True),
        ("invalid", False),
        ("injection", True),
        ("spam", True),
        ("model-failure", True),
    ],
)
def test_every_process_scenario_runs_without_keys_or_network(
    monkeypatch,
    scenario_name: str,
    expected_valid: bool,
) -> None:
    secret_names = (
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "DEEPSEEK_API_KEY",
        "NOTION_API_KEY",
        "BGE_API_BASE_URL",
    )

    for secret_name in secret_names:
        monkeypatch.delenv(secret_name, raising=False)

    result = process_scenario(scenario_name)

    assert result.validation_result.is_valid is expected_valid
    assert (
        result.cleaned_lead.external_lead_id == SCENARIO_PAYLOADS[scenario_name]["external_lead_id"]
    )

    if expected_valid:
        assert result.analysis_result is not None
    else:
        assert result.analysis_result is None
