from typing import Any

from lead_cleaner.services.llm_errors import (
    LLMRefusalError,
    LLMResponseIncompleteError,
)


def ensure_complete_structured_response(
    response: Any,
    *,
    operation: str,
) -> None:
    """Reject incomplete or refused Responses API output before parsing it."""

    if getattr(response, "status", None) == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None) or "unknown"
        raise LLMResponseIncompleteError(f"{operation} was incomplete: {reason}.")

    for output_item in getattr(response, "output", ()) or ():
        if getattr(output_item, "type", None) != "message":
            continue

        for content_item in getattr(output_item, "content", ()) or ():
            if getattr(content_item, "type", None) == "refusal":
                raise LLMRefusalError(f"Model refused {operation.lower()}.")
