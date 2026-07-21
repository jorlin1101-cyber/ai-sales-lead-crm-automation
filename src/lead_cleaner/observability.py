import json
import logging
import re
from enum import Enum
from typing import Any


LOGGER_NAME = "lead_cleaner"
logger = logging.getLogger(LOGGER_NAME)
logger.setLevel(logging.INFO)

_SAFE_FIELDS = frozenset(
    {
        "request_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
        "app_mode",
        "execution_mode",
        "analysis_method",
        "fallback_reason",
        "validation_status",
        "intent_level",
        "disposition",
        "policy_version",
        "source_count",
        "retrieval_method",
        "recommendation_method",
        "error_code",
        "error_type",
    }
)
_EVENT_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_SECRET_PATTERN = re.compile(
    r"(?i)(?:Bearer\s+\S+|sk-[A-Za-z0-9_-]{8,}|ntn_[A-Za-z0-9_-]{8,}|"
    r"(?:api[_-]?key|secret|token|password)\s*[:=]\s*\S+)"
)


def _normalize_safe_value(key: str, value: Any) -> str | int | float | bool | None:
    if key not in _SAFE_FIELDS:
        return "[REDACTED]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Enum):
        value = value.value
    text = str(value)[:200]
    if _EMAIL_PATTERN.search(text) or _SECRET_PATTERN.search(text):
        return "[REDACTED]"
    return text


def build_log_payload(event: str, **fields: Any) -> dict[str, Any]:
    safe_event = event if _EVENT_PATTERN.fullmatch(event) else "invalid_event"
    return {
        "event": safe_event,
        **{key: _normalize_safe_value(key, value) for key, value in fields.items()},
    }


def log_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Emit one JSON event containing only allow-listed, sanitized fields."""

    payload = build_log_payload(event, **fields)
    logger.log(
        level,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
    )
