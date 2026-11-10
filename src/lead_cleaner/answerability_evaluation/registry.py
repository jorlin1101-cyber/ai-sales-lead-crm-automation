"""Fixed version registry: callers cannot select arbitrary or weaker policy paths."""

from typing import Final

ACTIVE_PROTOCOL: Final = "p0-02.v2"


def protocol_spec(protocol_id: str) -> dict[str, str]:
    if protocol_id not in {"p0-02.v1", "p0-02.v2"}:
        raise ValueError("Unsupported answerability protocol")
    version = {"p0-02.v1": "v1", "p0-02.v2": "v2"}[protocol_id]
    return {
        "protocol_id": protocol_id,
        "schema_version": f"answerability-eval.{version}",
        "cases_schema": f"answerability-cases.{version}",
        "knowledge_schema": f"answerability-knowledge.{version}",
        "dataset_version": f"p0-02-cases.{version}",
        "rubric_version": f"answerability-rubric.{version}",
        "data_directory": "data/answerability_eval" + ("/v2" if version == "v2" else ""),
        "policy_path": f"config/quality_answerability.{version}.json",
        "trust_path": f"config/quality_answerability_trust.{version}.json",
        "index_path": f"config/quality_answerability_baseline_index.{version}.json",
        "issues_path": f"config/quality_answerability_known_issues.{version}.json",
        "baseline_directory": f"reports/quality/baselines/{protocol_id}",
    }
