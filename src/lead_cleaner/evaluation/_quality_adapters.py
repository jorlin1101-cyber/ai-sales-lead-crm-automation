"""Production entry-point adapters. This module does not repair business decisions."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lead_cleaner.api.main import create_app
from lead_cleaner.evaluation._quality_runtime import RecordedClient, isolated_settings
from lead_cleaner.rag.retriever import RagRetrievalOutcome
from lead_cleaner.rag.schemas import RetrievedChunk
from lead_cleaner.schemas.conversation import (
    ConversationFact,
    ConversationMessageRequest,
    ReplyDraft,
)
from lead_cleaner.schemas.policy import LeadFeatures
from lead_cleaner.services.conversation_llm import (
    ConversationLLMError,
    QwenConversationLLM,
    apply_understanding,
)
from lead_cleaner.services.conversation_memory import cumulative_features, merge_facts

INFRASTRUCTURE_CODES = {
    "timeout",
    "authentication_error",
    "provider_error",
    "unexpected_client_error",
}


def observation(
    mode: str,
    case_id: str,
    probe_id: str,
    checkpoint: str,
    trial_id: str,
    data: dict[str, Any],
    stages: list[dict[str, Any]] | None = None,
    execution_status: str = "completed",
    error_type: str | None = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "case_id": case_id,
        "probe_id": probe_id,
        "checkpoint": checkpoint,
        "trial_id": trial_id,
        "execution_status": execution_status,
        "data": data,
        "stages": deepcopy(stages or []),
        "error_type": error_type,
    }


def facts_from(values: list[dict[str, Any]]) -> list[ConversationFact]:
    return [ConversationFact.model_validate(value) for value in values]


def finish_boundary(recorded: RecordedClient, error: ConversationLLMError | None) -> None:
    if not recorded.records:
        return
    latest = recorded.records[-1]
    latest["validation_result"] = "accepted" if error is None else "rejected"
    if latest["provider_execution"] != "succeeded":
        latest["validation_result"] = "not_reached"
    if error is not None and latest["error_type"] is None:
        latest["error_type"] = error.code


def understanding_data(
    payload: dict[str, Any],
    qwen: QwenConversationLLM,
    recorded: RecordedClient,
) -> tuple[dict[str, Any], str, str | None]:
    previous = facts_from(payload.get("previous_facts", []))
    incoming = facts_from(payload.get("incoming_facts", []))
    message_id = payload.get("current_message_id", "m2")
    data: dict[str, Any] = {
        "current_message_id": message_id,
        "previous_facts": payload.get("previous_facts", []),
        "rejected": False,
        "rejection_code": None,
    }
    try:
        result = qwen.understand(
            payload["message"],
            previous,
            payload.get("pending_questions", []),
            payload.get("history", []),
        )
        old, updates = apply_understanding(previous, incoming, result, message_id)
        facts = merge_facts(old, updates, payload["message"])
        data.update(
            candidate=result.model_dump(mode="json"),
            facts=[item.model_dump(mode="json") for item in facts],
        )
        finish_boundary(recorded, None)
        return data, "completed", None
    except ConversationLLMError as error:
        finish_boundary(recorded, error)
        data.update(rejected=True, rejection_code=error.code, facts=[])
        return data, "error" if error.code in INFRASTRUCTURE_CODES else "completed", error.code


def message_payload(case_id: str, message: str, turn: int, channel: str = "web_chat") -> dict:
    return {
        "channel": channel,
        "source": "p0_quality_eval",
        "external_conversation_id": f"quality-{case_id}",
        "external_message_id": f"quality-{case_id}-{turn}",
        "sender_name": "Synthetic evaluation customer",
        "sender_email": "eval@example.com",
        "company_name": None,
        "subject": "Travel enquiry" if channel == "email" else None,
        "message": message,
        "source_authorized": True,
    }


def generation_data(
    payload: dict[str, Any],
    qwen: QwenConversationLLM,
    recorded: RecordedClient,
) -> tuple[dict[str, Any], str, str | None]:
    request = ConversationMessageRequest.model_validate(
        message_payload("boundary", payload["message"], 1)
    )
    chunks = [RetrievedChunk.model_validate(item) for item in payload["chunks"]]
    draft = ReplyDraft(
        draft_id="quality-draft",
        channel=request.channel,
        conversation_id="quality-conversation",
        turn_number=1,
        status="ready_for_review",
        body_text="",
        display_text="",
        policy_version="policy-v1",
        answer_intents=["pricing"],
    )
    data: dict[str, Any] = {
        "rejected": False,
        "rejection_code": None,
        "retrieval": {"sources": [item.model_dump(mode="json") for item in chunks]},
    }
    try:
        result = qwen.compose(
            request,
            draft,
            facts_from(payload.get("previous_facts", [])),
            chunks,
            payload.get("language", "zh"),
        )
        data["reply"] = result.model_dump(mode="json")
        finish_boundary(recorded, None)
        return data, "completed", None
    except ConversationLLMError as error:
        finish_boundary(recorded, error)
        data.update(rejected=True, rejection_code=error.code, reply=None)
        return data, "error" if error.code in INFRASTRUCTURE_CODES else "completed", error.code


def memory_data(payload: dict[str, Any]) -> dict[str, Any]:
    if "previous_features" in payload:
        # The annotation and natural message are evidence for grading only. The
        # existing function receives its actual interface: no hidden retract flag.
        previous = LeadFeatures.model_validate(payload["previous_features"])
        current = LeadFeatures.model_validate(payload["current_features"])
        result = cumulative_features(previous, current, facts_from(payload.get("facts", [])))
        return {
            "features": result.model_dump(mode="json"),
            "input_features": current.model_dump(mode="json"),
            "interface_has_retraction_signal": False,
            "annotation": payload.get("annotation"),
            "message": payload["message"],
        }
    facts = merge_facts(
        facts_from(payload["previous_facts"]),
        facts_from(payload["incoming_facts"]),
        payload["message"],
    )
    return {
        "facts": [item.model_dump(mode="json") for item in facts],
        "current_message_id": payload["current_message_id"],
    }


class FixtureRetriever:
    def __init__(self, chunks: list[dict[str, Any]]):
        self.chunks = [RetrievedChunk.model_validate(value) for value in chunks]

    def retrieve(self, query: str) -> RagRetrievalOutcome:
        return RagRetrievalOutcome(chunks=self.chunks, retrieval_method="keyword_rrf")

    def product_manuals(self, region: str) -> list[RetrievedChunk]:
        return []


def api_data(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "response": response,
        "facts": response.get("confirmed_facts", []),
        "reply": response.get("reply_draft"),
        "retrieval": response.get("retrieval", {}),
        "state": response.get("state"),
        "rejected": False,
        "rejection_code": None,
    }


def _finish_api_stages(
    recorded: RecordedClient,
    trace: dict[str, str],
    turn: int,
    expected_stages: list[str],
) -> None:
    for stage in ("understanding", "generation"):
        matches = [
            item for item in recorded.records if item["turn"] == turn and item["stage"] == stage
        ]
        state = trace.get(stage, "not_called")
        if not matches:
            recorded.records.append(
                {
                    "stage": stage,
                    "turn": turn,
                    "expected_to_run": stage in expected_stages,
                    "provider_kind": recorded.provider_kind,
                    "provider_execution": "not_called",
                    "validation_result": "not_reached",
                    "call_count": 0,
                    "retry_count": 0,
                    "fallback_used": False,
                    "error_type": None,
                    "upstream_blocked": stage == "generation"
                    and trace.get("understanding") != "succeeded",
                    "usage": "unknown",
                }
            )
            continue
        for item in matches:
            item["expected_to_run"] = stage in expected_stages
            item["fallback_used"] = state.startswith("fallback:")
            if item["provider_execution"] == "succeeded":
                item["validation_result"] = "accepted" if state == "succeeded" else "rejected"
            if state.startswith("fallback:") and item["error_type"] is None:
                item["error_type"] = state.split(":", 1)[1]


def readback(database: Path, case_id: str, response: dict[str, Any]) -> dict[str, Any]:
    # A new read-only SQLite connection is opened after the application's own
    # connection is closed. Query execution, including absence, is recorded.
    with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        conv = connection.execute(
            "SELECT id FROM conversations WHERE external_conversation_id = ?",
            (f"quality-{case_id}",),
        ).fetchone()
        cid = conv["id"] if conv else "__absent__"
        rows = connection.execute(
            "SELECT * FROM conversation_facts WHERE conversation_id = ? ORDER BY fact_key",
            (cid,),
        ).fetchall()
        messages = connection.execute(
            "SELECT id, external_message_id FROM conversation_messages WHERE conversation_id = ? ORDER BY turn_number",
            (cid,),
        ).fetchall()
        drafts = connection.execute(
            "SELECT draft_json, status FROM reply_drafts WHERE conversation_id = ? ORDER BY created_at",
            (cid,),
        ).fetchall()
    facts = [
        dict(
            key=row["fact_key"],
            value=row["fact_value"],
            status=row["status"],
            confidence=row["confidence"],
            source_message_id=row["source_message_id"],
        )
        for row in rows
    ]
    mapping = {row["external_message_id"]: row["id"] for row in messages}
    reply = json.loads(drafts[-1]["draft_json"]) if drafts else None

    def sort_key(fact: dict[str, Any]) -> str:
        return fact["key"]

    api_facts = response.get("confirmed_facts", [])
    return {
        "facts": facts,
        "reply": reply,
        "query_executed": True,
        "record_exists": bool(facts or drafts),
        "conversation_exists": bool(conv),
        "message_ids": mapping,
        "current_message_id": list(mapping.values())[-1] if mapping else None,
        "stored_draft_status": drafts[-1]["status"] if drafts else None,
        "retrieval": response.get("retrieval", {}),
        "rejected": False,
        "rejection_code": None,
        "api_comparison": {
            "facts_match": sorted(facts, key=sort_key) == sorted(api_facts, key=sort_key),
            "draft_match": reply == response.get("reply_draft"),
            "source_links_valid": all(f["source_message_id"] in mapping.values() for f in facts),
        },
    }


def run_api(
    project_root: Path,
    database: Path,
    case: dict[str, Any],
    probe: str,
    qwen: QwenConversationLLM | None,
    recorded: RecordedClient | None,
) -> tuple[dict[str, Any], dict[str, Any] | None, str, str | None]:
    payload = case["payload"]
    turns = payload.get("api_turns", payload.get("turns", []))
    response: dict[str, Any] = {}
    turn_observations: list[dict[str, Any]] = []
    error_type = None
    status = "completed"
    settings = isolated_settings(project_root, database)
    app = create_app(settings=settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        if qwen is not None:
            app.state.conversation_llm = qwen
        if probe == "api" and payload.get("chunks"):
            app.state.rag_retriever = FixtureRetriever(payload["chunks"])
        for turn, message in enumerate(turns, 1):
            if recorded:
                recorded.turn = turn
            result = client.post(
                "/conversations/messages",
                json=message_payload(
                    case["case_id"], message, turn, payload.get("channel", "web_chat")
                ),
            )
            if result.status_code != 200:
                status, error_type = "error", f"http_{result.status_code}"
                turn_observations.append({"turn": turn, "http_status": result.status_code})
                break
            response = result.json()
            turn_observations.append(
                {"turn": turn, "http_status": result.status_code, "response": response}
            )
            if recorded:
                expected = (
                    ["understanding"]
                    if case["case_id"] == "F01"
                    else ["understanding", "generation"]
                )
                _finish_api_stages(recorded, response.get("llm_trace", {}), turn, expected)
                if recorded.budget.exhausted:
                    error_type = "request_budget_exhausted"
                    break
    data = api_data(response)
    data["turns"] = turn_observations
    saved = readback(database, case["case_id"], response) if probe == "api" else None
    if saved is not None:
        data.update(
            message_ids=saved["message_ids"], current_message_id=saved["current_message_id"]
        )
    return data, saved, status, error_type
