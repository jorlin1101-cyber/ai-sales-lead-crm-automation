import re
from contextvars import ContextVar, Token
from uuid import uuid4

from fastapi import Request


REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_request_id_context: ContextVar[str | None] = ContextVar(
    "lead_cleaner_request_id",
    default=None,
)


def resolve_request_id(candidate: str | None) -> str:
    """Keep a safe caller ID or create a server-owned UUID."""

    if candidate is not None:
        normalized = candidate.strip()
        if _REQUEST_ID_PATTERN.fullmatch(normalized):
            return normalized
    return str(uuid4())


def set_request_id(request_id: str) -> Token[str | None]:
    return _request_id_context.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id_context.reset(token)


def get_request_id() -> str | None:
    return _request_id_context.get()


def request_id_from_request(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    return resolve_request_id(None)
