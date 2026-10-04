"""Isolated transport and SDK recording used only by the quality runner."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit

from lead_cleaner.config import AppMode, RagBackend, Settings


class QualityConfigurationError(ValueError):
    """The requested experiment is not configured; do not substitute another mode."""


class RequestBudgetExceeded(RuntimeError):
    """The runner's shared hard request limit has been reached."""


@dataclass
class RequestBudget:
    maximum: int
    used: int = 0
    exhausted: bool = False

    def consume(self) -> None:
        if self.used >= self.maximum:
            self.exhausted = True
            raise RequestBudgetExceeded("request_budget_exhausted")
        self.used += 1


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def append_journal(path: Path | None, event: dict[str, Any]) -> None:
    """Flush diagnostic evidence immediately; journals are never formal reports."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"recorded_at": datetime.now(UTC).isoformat(), **event}
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()


def isolated_settings(project_root: Path, database_path: Path) -> Settings:
    # Explicit values take precedence over process environment as well as .env.
    # Reset every field so unrelated inherited invalid credentials cannot leak in.
    defaults = {
        name: field.get_default(call_default_factory=True)
        for name, field in Settings.model_fields.items()
    }
    defaults.update(
        app_mode=AppMode.RULE_ONLY,
        allow_network=False,
        rag_backend=RagBackend.KEYWORD_RRF,
        rag_required=True,
        knowledge_chunks_path=project_root / "data/knowledge_snapshot/knowledge_chunks.json",
        conversation_database_url=None,
        conversation_db_path=database_path,
        conversation_auto_create_schema=True,
        conversation_llm_enabled=False,
        grounded_recommendation_enabled=False,
        notion_crm_enabled=False,
        service_access_mode="local",
    )
    return Settings(**{"_env_file": None, **defaults})


class NetworkGuard:
    """Deny non-local sockets, or allow only the configured live target.

    Windows asyncio uses loopback sockets to implement socketpair. Those framework
    connections remain allowed; production outbound writers are separately disabled.
    The guard belongs to the standalone runner and does not rely on pytest plugins.
    """

    def __init__(self, target_url: str | None = None):
        parsed = urlsplit(target_url) if target_url else None
        if parsed and (
            parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
        ):
            raise QualityConfigurationError("live target must be HTTPS without credentials")
        self.target = (parsed.hostname, parsed.port or 443) if parsed else None
        self.resolved_targets: set[tuple[str, int]] = set()
        self.blocked_attempts = 0
        self.loopback_connections = 0
        self.target_connections = 0
        self._stack = ExitStack()

    @staticmethod
    def _local(host: str) -> bool:
        if host.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
        except ValueError:
            return False

    def _check(self, address: Any) -> None:
        if isinstance(address, str):  # AF_UNIX, used by the local async runtime.
            return
        host, port = str(address[0]), int(address[1])
        if self._local(host):
            self.loopback_connections += 1
        elif self.target == (host, port) or (host, port) in self.resolved_targets:
            self.target_connections += 1
        else:
            self.blocked_attempts += 1
            raise OSError("quality runner blocked non-target external connection")

    def __enter__(self) -> NetworkGuard:
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_getaddrinfo = socket.getaddrinfo

        def connect(sock: socket.socket, address: Any) -> Any:
            self._check(address)
            return original_connect(sock, address)

        def connect_ex(sock: socket.socket, address: Any) -> Any:
            self._check(address)
            return original_connect_ex(sock, address)

        def getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
            name = host.decode() if isinstance(host, bytes) else str(host)
            if host is not None and not self._local(name):
                if self.target != (name, int(port)):
                    self.blocked_attempts += 1
                    raise OSError("quality runner blocked non-target DNS lookup")
            result = original_getaddrinfo(host, port, *args, **kwargs)
            if self.target == (name, int(port or 0)):
                self.resolved_targets.update((str(item[4][0]), int(item[4][1])) for item in result)
            return result

        self._stack.enter_context(patch.object(socket.socket, "connect", connect))
        self._stack.enter_context(patch.object(socket.socket, "connect_ex", connect_ex))
        self._stack.enter_context(patch.object(socket, "getaddrinfo", getaddrinfo))
        return self

    def __exit__(self, *args: Any) -> None:
        self._stack.__exit__(*args)

    def summary(self) -> dict[str, Any]:
        return {
            "external_blocked": self.blocked_attempts,
            "loopback_connections": self.loopback_connections,
            "target_connections": self.target_connections,
            "target_host": self.target[0] if self.target else None,
        }


class QueueClient:
    """Strict SDK response queue: exhaustion is an error, never an empty success."""

    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.closed = False

    def create(self, **kwargs: Any) -> Any:
        if not self.responses:
            raise RuntimeError("mock_response_queue_exhausted")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        content = item(**kwargs) if callable(item) else item
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content=json.dumps(content, ensure_ascii=False), refusal=None
                    ),
                )
            ],
            usage=None,
        )

    def close(self) -> None:
        self.closed = True


class RecordedClient:
    """Record the actual SDK boundary without changing prompts or model output."""

    def __init__(
        self,
        client: Any,
        budget: RequestBudget,
        provider_kind: str,
        journal_path: Path | None = None,
        context: dict[str, str] | None = None,
    ):
        self.client = client
        self.budget = budget
        self.provider_kind = provider_kind
        self.journal_path = journal_path
        self.context = dict(context or {})
        self.records: list[dict[str, Any]] = []
        self.turn = 1
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs: Any) -> Any:
        messages = kwargs.get("messages", [])
        payload = json.loads(messages[-1]["content"])
        stage = "generation" if "evidence" in payload else "understanding"
        output_schema_hash = "unknown"
        system_text = messages[0]["content"]
        if "Schema: " in system_text:
            try:
                output_schema_hash = digest(json.loads(system_text.rsplit("Schema: ", 1)[1]))
            except (ValueError, TypeError):
                pass
        record: dict[str, Any] = {
            "stage": stage,
            "turn": self.turn,
            "expected_to_run": True,
            "provider_kind": self.provider_kind,
            "provider_execution": "not_called",
            "validation_result": "not_reached",
            "call_count": 0,
            "retry_count": 0,
            "fallback_used": False,
            "error_type": None,
            "system_prompt_sha256": digest(system_text),
            "output_schema_sha256": output_schema_hash,
            "input_sha256": digest(payload),
            "request_sha256": digest(kwargs),
            "model": kwargs.get("model"),
            "max_tokens": kwargs.get("max_tokens"),
            "temperature": kwargs.get("temperature"),
            "usage": "unknown",
        }
        self.records.append(record)
        started = perf_counter()
        try:
            self.budget.consume()
            record["call_count"] = 1
            response = self.client.chat.completions.create(**kwargs)
            record["provider_execution"] = "succeeded"
            choices = getattr(response, "choices", [])
            if isinstance(choices, list):
                record["response_choices"] = [
                    {
                        "finish_reason": choice.finish_reason,
                        "content": getattr(choice.message, "content", None),
                        "refusal": getattr(choice.message, "refusal", None),
                    }
                    for choice in choices
                ]
                record["response_sha256"] = digest(record["response_choices"])
            usage = getattr(response, "usage", None)
            if usage is not None:
                values = usage.model_dump() if hasattr(usage, "model_dump") else vars(usage)
                record["usage"] = {
                    name: values.get(name)
                    for name in ("prompt_tokens", "completion_tokens", "total_tokens")
                }
            return response
        except BaseException as error:
            record["provider_execution"] = "error"
            record["error_type"] = (
                "request_budget_exhausted"
                if isinstance(error, RequestBudgetExceeded)
                else type(error).__name__
            )
            raise
        finally:
            record["duration_ms"] = round((perf_counter() - started) * 1000, 3)
            append_journal(
                self.journal_path, {"event": "model_call", **self.context, "record": record}
            )

    def close(self) -> None:
        self.client.close()
