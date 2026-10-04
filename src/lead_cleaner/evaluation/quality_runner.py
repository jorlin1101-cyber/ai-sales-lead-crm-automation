"""Run frozen P0-01 scenarios against isolated production entry points.

Observations contain what happened, not grades. No actual model is called unless
live is selected, explicitly permitted, and configured with a credential.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from openai import DefaultHttpxClient, OpenAI

from lead_cleaner.evaluation._quality_adapters import (
    generation_data,
    memory_data,
    observation,
    run_api,
    understanding_data,
)
from lead_cleaner.evaluation._quality_runtime import (
    NetworkGuard,
    QualityConfigurationError,
    QueueClient,
    RecordedClient,
    RequestBudget,
    append_journal,
    digest,
    isolated_settings,
)
from lead_cleaner.services.conversation_llm import QwenConversationLLM

MODES = ("rule_only", "mocked_model", "live")
ADAPTERS = frozenset({"conversation_api", "understanding", "generation", "memory"})


def _root(path: str | Path | None) -> Path:
    return Path(path).resolve() if path is not None else Path(__file__).resolve().parents[3]


def _legacy_case(case: dict[str, Any]) -> dict[str, Any]:
    assertions = [
        {
            "assertion_id": "legacy_business_requirements",
            "probe_id": "main",
            "checkpoint": "result",
            "observation_scope": "api",
            "check": "conversation_legacy",
            "params": {"case": case},
            "mandatory": True,
            "severity": "major",
            "manual_review": True,
            "applicable_modes": ["rule_only", "live"],
        }
    ]
    for stage in ("understanding", "generation"):
        assertions.append(
            {
                "assertion_id": f"{stage}_executed",
                "probe_id": "main",
                "checkpoint": "result",
                "observation_scope": "api",
                "check": "model_stage",
                "params": {"stage": stage, "expected_to_run": True},
                "mandatory": True,
                "severity": "major",
                "manual_review": False,
                "applicable_modes": ["live"],
            }
        )
    return {
        "case_id": case["id"],
        "case_version": 1,
        "family": "legacy_conversation",
        "language": "zh",
        "source": "synthetic",
        "applicable_modes": ["rule_only", "live"],
        "adapter": "conversation_api",
        "payload": {"turns": case["turns"], "channel": case["channel"]},
        "assertions": assertions,
        "review_status": case.get("review_status", "draft"),
        **{
            name: case[name]
            for name in ("reviewer", "reviewed_at", "review_reason")
            if name in case
        },
        "related_cases": [],
        "relation_type": None,
    }


def load_cases(project_root: str | Path | None = None) -> list[dict[str, Any]]:
    root = _root(project_root)

    def read_jsonl(path: Path) -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    cases = [
        _legacy_case(item)
        for item in read_jsonl(root / "data/evals/multi_turn_conversations.jsonl")
    ]
    cases.extend(read_jsonl(root / "data/evals/p0_quality_cases.v1.jsonl"))
    ids = [item["case_id"] for item in cases]
    if len(ids) != len(set(ids)):
        raise QualityConfigurationError("duplicate case_id")
    if any(case["adapter"] not in ADAPTERS for case in cases):
        raise QualityConfigurationError("unregistered case adapter")
    return cases


def applicable_assertions(case: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    return [item for item in case["assertions"] if mode in item.get("applicable_modes", MODES)]


def _probe_checkpoints(case: dict[str, Any], mode: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for assertion in applicable_assertions(case, mode):
        probe = assertion.get("probe_id", "main")
        checkpoint = assertion.get("checkpoint", "result")
        if checkpoint not in values.setdefault(probe, []):
            values[probe].append(checkpoint)
    return values


def _live_configuration(
    mode: str,
    allow_network: bool,
    config: dict[str, Any],
    factory: Callable | None,
) -> tuple[str, str | None]:
    if mode != "live":
        return "mock", None
    if factory is not None:
        return "mock", None
    if not allow_network:
        raise QualityConfigurationError("live requires explicit allow_network")
    if not str(config.get("api_key", "")).strip():
        raise QualityConfigurationError("live requires an explicit API credential")
    timeout = config.get("timeout", 30.0)
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
        raise QualityConfigurationError("live timeout must be within (0, 60] seconds")
    if not str(config.get("model", "qwen3.7-plus")).strip():
        raise QualityConfigurationError("live model must not be empty")
    target = config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    return "real", target


def _client(
    case: dict[str, Any],
    trial: str,
    probe: str,
    mode: str,
    config: dict[str, Any],
    factory: Callable[[dict[str, Any], str, str], Any] | None,
) -> Any:
    if mode == "live":
        if factory is not None:
            return factory(deepcopy(case), trial, probe)
        timeout = float(config.get("timeout", 30))
        return OpenAI(
            api_key=config["api_key"],
            base_url=config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            timeout=timeout,
            max_retries=0,
            http_client=DefaultHttpxClient(timeout=timeout, trust_env=False),
        )
    payload = case["payload"]
    responses = payload["api_mock_responses"] if probe == "api" else [payload["mock_response"]]
    return QueueClient(deepcopy(responses))


def _execute_probe(
    case: dict[str, Any],
    probe: str,
    mode: str,
    trial: str,
    root: Path,
    work: Path,
    recorded: RecordedClient | None,
    model: str,
) -> list[dict[str, Any]]:
    qwen = QwenConversationLLM(cast(Any, recorded), model) if recorded is not None else None
    adapter = "conversation_api" if probe == "api" else case["adapter"]
    saved = None
    if adapter == "conversation_api":
        data, saved, status, error = run_api(
            root, work / "conversation.sqlite3", case, probe, qwen, recorded
        )
    elif adapter == "understanding" and qwen is not None and recorded is not None:
        data, status, error = understanding_data(case["payload"], qwen, recorded)
    elif adapter == "generation" and qwen is not None and recorded is not None:
        data, status, error = generation_data(case["payload"], qwen, recorded)
    elif adapter == "memory":
        data, status, error = memory_data(case["payload"]), "completed", None
    else:
        raise QualityConfigurationError("adapter requires a configured model client")
    stages = recorded.records if recorded else []
    values = [
        observation(mode, case["case_id"], probe, "result", trial, data, stages, status, error)
    ]
    if saved is not None:
        values.append(
            observation(
                mode, case["case_id"], probe, "persisted", trial, saved, stages, status, error
            )
        )
    return values


def run_quality_suite(
    mode: str,
    *,
    project_root: str | Path | None = None,
    work_root: str | Path | None = None,
    cases: list[dict[str, Any]] | None = None,
    trials: int | None = None,
    max_requests: int = 60,
    allow_network: bool = False,
    live_config: dict[str, Any] | None = None,
    live_client_factory: Callable[[dict[str, Any], str, str], Any] | None = None,
    journal_path: str | Path | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise QualityConfigurationError("unknown quality mode")
    expected_trials = 3 if mode == "live" else 1
    if trials is not None and trials != expected_trials:
        raise QualityConfigurationError("trial count differs from the frozen protocol")
    if not isinstance(max_requests, int) or max_requests < 1:
        raise QualityConfigurationError("max_requests must be a positive integer")
    root = _root(project_root)
    selected = deepcopy(cases if cases is not None else load_cases(root))
    selected = [case for case in selected if mode in case["applicable_modes"]]
    if any(case["adapter"] not in ADAPTERS for case in selected):
        raise QualityConfigurationError("unregistered case adapter")
    if len({case["case_id"] for case in selected}) != len(selected):
        raise QualityConfigurationError("duplicate case_id")
    config = dict(live_config or {})
    provider_kind, target = _live_configuration(mode, allow_network, config, live_client_factory)
    model = config.get("model", "qwen3.7-plus") if provider_kind == "real" else "quality-mock"
    work_root_path = (
        Path(work_root).resolve() if work_root is not None else root / "data/runtime/quality-work"
    )
    work_root_path.mkdir(parents=True, exist_ok=True)
    expected_keys = [
        [
            mode,
            case["case_id"],
            assertion.get("probe_id", "main"),
            assertion.get("checkpoint", "result"),
            assertion["assertion_id"],
            str(trial),
        ]
        for case in selected
        for trial in range(1, expected_trials + 1)
        for assertion in applicable_assertions(case, mode)
    ]
    if len(expected_keys) != len({tuple(key) for key in expected_keys}):
        raise QualityConfigurationError("duplicate assertion key")
    journal = Path(journal_path) if journal_path is not None else None
    budget = RequestBudget(max_requests)
    observations: list[dict[str, Any]] = []
    call_records: list[dict[str, Any]] = []
    guard = NetworkGuard(target)
    with guard:
        for case in selected:
            for trial_number in range(1, expected_trials + 1):
                trial = str(trial_number)
                for probe, checkpoints in _probe_checkpoints(case, mode).items():
                    if budget.exhausted:
                        observations.extend(
                            observation(
                                mode,
                                case["case_id"],
                                probe,
                                checkpoint,
                                trial,
                                {},
                                [],
                                "not_run",
                                "request_budget_exhausted",
                            )
                            for checkpoint in checkpoints
                        )
                        for value in observations[-len(checkpoints) :]:
                            append_journal(journal, {"event": "observation", "observation": value})
                        continue
                    recorded = None
                    try:
                        if mode != "rule_only":
                            sdk = _client(case, trial, probe, mode, config, live_client_factory)
                            recorded = RecordedClient(
                                sdk,
                                budget,
                                provider_kind,
                                journal,
                                {
                                    "mode": mode,
                                    "case_id": case["case_id"],
                                    "probe_id": probe,
                                    "trial_id": trial,
                                },
                            )
                        # tempfile owns only the fresh directory it creates under the
                        # caller-specified work root. It never removes pre-existing data.
                        with tempfile.TemporaryDirectory(
                            prefix="case-", dir=work_root_path
                        ) as temporary:
                            work = Path(temporary).resolve()
                            if work_root_path not in work.parents:
                                raise QualityConfigurationError("temporary path escaped work root")
                            values = _execute_probe(
                                case, probe, mode, trial, root, work, recorded, model
                            )
                        observations.extend(values)
                        for value in values:
                            append_journal(journal, {"event": "observation", "observation": value})
                    except Exception as error:
                        observations.extend(
                            observation(
                                mode,
                                case["case_id"],
                                probe,
                                checkpoint,
                                trial,
                                {},
                                recorded.records if recorded else [],
                                "error",
                                type(error).__name__,
                            )
                            for checkpoint in checkpoints
                        )
                        for value in observations[-len(checkpoints) :]:
                            append_journal(journal, {"event": "observation", "observation": value})
                    finally:
                        if recorded is not None:
                            call_records.extend(
                                dict(item, case_id=case["case_id"], probe_id=probe, trial_id=trial)
                                for item in recorded.records
                            )
                            recorded.close()
    calls = [item for item in call_records if item["call_count"]]
    settings = isolated_settings(root, work_root_path / "unused-settings-description.sqlite3")
    settings_fields = (
        "app_mode",
        "allow_network",
        "rag_backend",
        "rag_required",
        "rag_top_k",
        "rag_candidate_top_k",
        "conversation_auto_create_schema",
        "conversation_llm_enabled",
        "grounded_recommendation_enabled",
        "notion_crm_enabled",
        "service_access_mode",
    )
    effective_settings = settings.model_dump(mode="json", include=set(settings_fields))
    endpoint = urlsplit(target) if target else None
    metadata = {
        "runner_version": "p0-quality-runner.v1",
        "adapter_version": "p0-production-adapters.v1",
        "effective_settings": effective_settings,
        "model_endpoint": urlunsplit((endpoint.scheme, endpoint.netloc, endpoint.path, "", ""))
        if endpoint
        else None,
        "model_endpoint_sha256": digest(target) if target else None,
        "model_timeout_seconds": float(config.get("timeout", 30))
        if provider_kind == "real"
        else None,
        "prompt_observation_status": "not_applicable"
        if mode == "rule_only"
        else "recorded_per_call",
        "output_schema_observation_status": "not_applicable"
        if mode == "rule_only"
        else "recorded_per_call",
        "mode": mode,
        "application_mode": "rule_only",
        "trial_count": expected_trials,
        "scenario_count": len(selected),
        "scenario_ids": [case["case_id"] for case in selected],
        "cases_sha256": digest(selected),
        "provider_kind": provider_kind if mode != "rule_only" else "none",
        "model": model if mode != "rule_only" else None,
        "real_model_calls": len(calls) if provider_kind == "real" else 0,
        "model_request_count": budget.used,
        "request_limit": max_requests,
        "budget_exhausted": budget.exhausted,
        "response_cache_enabled": False,
        "provider_max_retries": 0,
        "model_calls": call_records,
        "socket_guard": guard.summary(),
        "business_side_effects_enabled": False,
        "database_isolation": "fresh SQLite per case/trial/probe; removed after observation",
        "live_simulated": mode == "live" and provider_kind == "mock",
        "partial_suite": len(selected) != {"rule_only": 10, "mocked_model": 12, "live": 10}[mode],
    }
    return {
        "observations": observations,
        "metadata": metadata,
        "expected_keys": expected_keys,
        "cases": selected,
    }
