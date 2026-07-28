from types import SimpleNamespace

import pytest

from lead_cleaner.services.llm_errors import (
    LLMRefusalError,
    LLMResponseIncompleteError,
)
from lead_cleaner.services.openai_response_guard import (
    ensure_complete_structured_response,
)


def test_guard_accepts_completed_message() -> None:
    response = SimpleNamespace(
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text")],
            )
        ],
    )

    ensure_complete_structured_response(response, operation="Test operation")


def test_guard_rejects_incomplete_response_with_reason() -> None:
    response = SimpleNamespace(
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        output=[],
    )

    with pytest.raises(LLMResponseIncompleteError, match="max_output_tokens"):
        ensure_complete_structured_response(response, operation="Test operation")


def test_guard_finds_refusal_inside_message_content() -> None:
    response = SimpleNamespace(
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="refusal", refusal="Cannot comply")],
            )
        ],
    )

    with pytest.raises(LLMRefusalError):
        ensure_complete_structured_response(response, operation="Test operation")


def test_guard_does_not_mistake_top_level_non_message_for_refusal() -> None:
    response = SimpleNamespace(
        status="completed",
        output=[SimpleNamespace(type="reasoning")],
    )

    ensure_complete_structured_response(response, operation="Test operation")
