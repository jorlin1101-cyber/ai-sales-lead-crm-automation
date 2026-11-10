"""Isolated, observed replay of the unchanged production conversation API.

The controlled model extracts provided evidence without access to labels. Its
results exercise integration and validation, not real model quality.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from lead_cleaner.api.main import create_app
from lead_cleaner.evaluation._quality_runtime import NetworkGuard, isolated_settings
from lead_cleaner.services import conversation_service
from lead_cleaner.services.conversation_llm import ConversationLLMError, QwenConversationLLM

MODES = ("rule_only", "mocked_model")


def _dump_chunks(chunks: list[Any]) -> list[dict[str, Any]]:
    return [chunk.model_dump(mode="json") for chunk in chunks]


def _stage(name: str, mode: str) -> dict[str, Any]:
    return {
        "stage": name,
        "applicable": mode == "mocked_model",
        "expected_to_run": False,
        "provider_kind": "mock" if mode == "mocked_model" else "none",
        "provider_execution": "not_called",
        "validation_result": "not_reached",
        "call_count": 0,
        "retry_count": 0,
        "fallback_used": False,
        "error_type": None,
        "not_called_reason": "rule_only" if mode == "rule_only" else "production_routing",
    }


def _empty_observation(protocol: str, mode: str, case: dict, turn: dict) -> dict[str, Any]:
    return {
        "protocol_id": protocol,
        "mode": mode,
        "case_id": case["case_id"],
        "probe_id": "conversation",
        "turn_id": turn["turn_id"],
        "trial_id": "1",
        "execution_status": "not_run",
        "error_type": None,
        "input_message": turn["message"],
        "history": [],
        "response": None,
        "facts": [],
        "state": None,
        "reply_text": None,
        "retrieved_chunks": [],
        "provided_context": [],
        "provided_context_rule": [],
        "provided_context_model": [],
        "stages": [_stage(name, mode) for name in ("understanding", "generation")],
        "api_status": None,
        "predicted_answerability": None,
        "model_calls": [],
        "retrieval_calls": [],
        "message_id_map": {},
    }


class ControlledClient:
    """One generic SDK substitute; it never sees case labels or future turns."""

    def __init__(self, recorder: dict[str, Any]):
        self.recorder = recorder
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs: Any) -> Any:
        payload = json.loads(kwargs["messages"][-1]["content"])
        record = {"request": kwargs, "response": None, "provider_execution": "started"}
        self.recorder["current"]["model_calls"].append(record)
        try:
            output = self.respond(payload)
            record.update(response=output, provider_execution="succeeded")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(
                            content=json.dumps(output, ensure_ascii=False), refusal=None
                        ),
                    )
                ],
                usage=None,
            )
        except BaseException as error:
            record.update(provider_execution="error", error_type=type(error).__name__)
            raise

    @staticmethod
    def respond(payload: dict[str, Any]) -> dict[str, Any]:
        if "evidence" not in payload:
            return {"updates": []}
        return {
            "paragraphs": [
                {"evidence_id": unit["evidence_id"], "text": unit["quote"][:600]}
                for unit in payload["evidence"][:3]
            ]
        }

    def close(self) -> None:
        pass


class DeclarativeControlledClient(ControlledClient):
    """V2 skips headings/questions in output, while recording every actual input."""

    @staticmethod
    def respond(payload: dict[str, Any]) -> dict[str, Any]:
        if "evidence" not in payload:
            return {"updates": []}
        candidates = [
            unit
            for unit in payload["evidence"]
            if unit["quote"].strip()
            and not unit["quote"].lstrip().startswith("#")
            and "?" not in unit["quote"]
            and "？" not in unit["quote"]
        ]
        # Empty paragraphs deliberately reach the real output validator/fallback.
        return {
            "paragraphs": [
                {"evidence_id": unit["evidence_id"], "text": unit["quote"][:600]}
                for unit in candidates[:3]
            ]
        }


class ObservedLLM(QwenConversationLLM):
    def __init__(self, recorder: dict[str, Any], protocol_id: str = "p0-02.v1"):
        client_type = DeclarativeControlledClient if protocol_id == "p0-02.v2" else ControlledClient
        super().__init__(client_type(recorder), "controlled-evidence-extractor")  # type: ignore[arg-type]
        self.recorder = recorder

    def _observe(self, name: str, operation: Any) -> Any:
        current = self.recorder["current"]
        stage = next(s for s in current["stages"] if s["stage"] == name)
        stage.update(expected_to_run=True, not_called_reason=None)
        before = len(current["model_calls"])
        try:
            result = operation()
            stage.update(validation_result="accepted")
            return result
        except ConversationLLMError as error:
            stage.update(validation_result="rejected", error_type=error.code, fallback_used=True)
            raise
        finally:
            calls = current["model_calls"][before:]
            stage["call_count"] = len(calls)
            stage["provider_execution"] = (
                "error"
                if any(c["provider_execution"] == "error" for c in calls)
                else "succeeded"
                if calls
                else "not_called"
            )
            if stage["provider_execution"] == "error":
                stage["validation_result"] = "not_reached"

    def understand(self, *args: Any, **kwargs: Any) -> Any:
        return self._observe(
            "understanding", lambda: super(ObservedLLM, self).understand(*args, **kwargs)
        )

    def compose(self, *args: Any, **kwargs: Any) -> Any:
        chunks = kwargs.get("chunks", args[3] if len(args) > 3 else [])
        self.recorder["current"]["provided_context_model"] = _dump_chunks(chunks)
        return self._observe(
            "generation", lambda: super(ObservedLLM, self).compose(*args, **kwargs)
        )


class RecordingRetriever:
    def __init__(self, delegate: Any, recorder: dict[str, Any]):
        self.delegate = delegate
        self.recorder = recorder

    def _record(self, method: str, query: str) -> Any:
        call: dict[str, Any] = {"method": method, "query": query, "results": [], "error_type": None}
        current = self.recorder["current"]
        current["retrieval_calls"].append(call)
        try:
            result = getattr(self.delegate, method)(query)
            chunks = result.chunks if method == "retrieve" else result
            call["results"] = _dump_chunks(chunks)
            if method == "retrieve":
                call["retrieval_method"] = result.retrieval_method
                if result.retrieval_method == "unavailable":
                    call["error_type"] = result.failure_reason or "retrieval_unavailable"
            seen = {c["chunk_id"] for c in current["retrieved_chunks"]}
            current["retrieved_chunks"].extend(
                c for c in call["results"] if c["chunk_id"] not in seen
            )
            return result
        except BaseException as error:
            call["error_type"] = type(error).__name__
            raise

    def retrieve(self, query: str) -> Any:
        return self._record("retrieve", query)

    def product_manuals(self, region: str) -> Any:
        return self._record("product_manuals", region)


def _message(case_id: str, turn_id: str, text: str) -> dict[str, Any]:
    return {
        "channel": "web_chat",
        "source": "answerability-eval",
        "external_conversation_id": f"answerability-{case_id}",
        "external_message_id": f"answerability-{case_id}-{turn_id}",
        "sender_name": "Evaluation Lead",
        "sender_email": "eval@example.com",
        "message": text,
        "source_authorized": True,
    }


def _finish(current: dict[str, Any], response: Any) -> None:
    current["api_status"] = response.status_code
    body = response.json()
    current["response"] = body
    if response.status_code != 200:
        current.update(execution_status="error", error_type=f"http_{response.status_code}")
        return
    current.update(
        execution_status="completed",
        facts=body["confirmed_facts"],
        state=body["state"],
        reply_text=body["reply_draft"]["body_text"],
    )
    # Keep the actual input of the composer that produced the returned draft.
    current["provided_context"] = current[
        "provided_context_model"
        if body["reply_draft"]["generation_method"] == "llm_grounded"
        else "provided_context_rule"
    ]
    failures = [s["error_type"] for s in current["stages"] if s["error_type"]]
    failures.extend(c["error_type"] for c in current["retrieval_calls"] if c["error_type"])
    if failures:
        current.update(execution_status="error", error_type=failures[0])


def run_observations(
    root: Path, dataset: dict[str, Any], mode: str, work_dir: Path
) -> list[dict[str, Any]]:
    """Replay only current/past messages, retaining every planned turn on failures."""
    if mode not in MODES:
        raise ValueError("answerability execution supports only rule_only and mocked_model")
    work_dir.mkdir(parents=True, exist_ok=True)
    observations = [
        _empty_observation(dataset["protocol_id"], mode, case, turn)
        for case in dataset["cases"]
        for turn in case["turns"]
    ]
    keys = [(o["case_id"], o["turn_id"]) for o in observations]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate case/turn observation identity")
    by_key = dict(zip(keys, observations, strict=True))
    recorder: dict[str, Any] = {}
    original_turn = conversation_service.ConversationService._process_turn
    original_compose = conversation_service.compose_grounded_reply

    def record_turn(service: Any, request: Any, **kwargs: Any) -> Any:
        current = recorder["current"]
        current["history"] = list(kwargs["recent_messages"])
        recorder["message_ids"][current["turn_id"]] = kwargs["message_id"]
        current["message_id_map"] = dict(recorder["message_ids"])
        return original_turn(service, request, **kwargs)

    def record_compose(*args: Any, **kwargs: Any) -> Any:
        recorder["current"]["provided_context_rule"] = _dump_chunks(kwargs["chunks"])
        return original_compose(*args, **kwargs)

    interrupted = False
    with NetworkGuard() as guard, ExitStack() as patches:
        patches.enter_context(
            patch.object(conversation_service.ConversationService, "_process_turn", record_turn)
        )
        patches.enter_context(
            patch.object(conversation_service, "compose_grounded_reply", record_compose)
        )
        for case in dataset["cases"]:
            if interrupted:
                break
            current = by_key[(case["case_id"], case["turns"][0]["turn_id"])]
            recorder.update(current=current, message_ids={})
            llm = None
            try:
                with TemporaryDirectory(prefix="answerability-", dir=work_dir) as temporary:
                    directory = Path(temporary)
                    knowledge_path = directory / "knowledge.json"
                    snapshot = dataset["snapshots"][case["snapshot_id"]]
                    knowledge_path.write_text(
                        json.dumps([c["chunk"] for c in snapshot["chunks"]], ensure_ascii=False),
                        encoding="utf-8",
                    )
                    settings = isolated_settings(
                        root, directory / "conversation.sqlite3"
                    ).model_copy(update={"knowledge_chunks_path": knowledge_path})
                    app = create_app(settings=settings)
                    with TestClient(app, raise_server_exceptions=False) as client:
                        app.state.rag_retriever = RecordingRetriever(
                            app.state.rag_retriever, recorder
                        )
                        if mode == "mocked_model":
                            llm = ObservedLLM(recorder, dataset["protocol_id"])
                            app.state.conversation_llm = llm
                        for turn in case["turns"]:
                            current = by_key[(case["case_id"], turn["turn_id"])]
                            recorder["current"] = current
                            response = client.post(
                                "/conversations/messages",
                                json=_message(case["case_id"], turn["turn_id"], turn["message"]),
                            )
                            _finish(current, response)
                            current["network_guard"] = guard.summary()
                            # A safe model fallback still persisted a valid turn. Replay onward.
                            if current["api_status"] != 200:
                                break
            except KeyboardInterrupt:
                current.update(execution_status="error", error_type="interrupted")
                interrupted = True
            except Exception as error:
                current.update(execution_status="error", error_type=type(error).__name__)
            finally:
                if llm is not None:
                    llm.close()
                current["network_guard"] = guard.summary()
        for observation in observations:
            if observation["execution_status"] == "not_run":
                observation["error_type"] = "interrupted" if interrupted else "previous_turn_failed"
    return observations
