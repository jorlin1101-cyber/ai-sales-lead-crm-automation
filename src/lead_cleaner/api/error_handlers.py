import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from lead_cleaner.api.request_context import (
    REQUEST_ID_HEADER,
    request_id_from_request,
)
from lead_cleaner.observability import log_event
from lead_cleaner.rag.retriever import RagUnavailableError
from lead_cleaner.services.llm_errors import (
    LLMAuthenticationError,
    LLMClientError,
    LLMConfigurationError,
)
from lead_cleaner.services.notion_crm import (
    NotionCrmError,
    NotionCrmNotConfiguredError,
    NotionCrmUnavailableError,
)


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    request_id = request_id_from_request(request)
    detail: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    if errors is not None:
        detail["errors"] = errors
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
        headers={REQUEST_ID_HEADER: request_id},
    )


def _safe_validation_errors(error: RequestValidationError) -> list[dict[str, Any]]:
    return [
        {
            "type": item.get("type", "validation_error"),
            "loc": list(item.get("loc", ())),
            "msg": item.get("msg", "Invalid request value."),
        }
        for item in error.errors()
    ]


def register_error_handlers(api: FastAPI) -> None:
    @api.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        log_event(
            "transport_error",
            level=logging.WARNING,
            request_id=request_id_from_request(request),
            error_code="request_validation_error",
            error_type=type(error).__name__,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
        return _error_response(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="request_validation_error",
            message="The request body does not match the API contract.",
            errors=_safe_validation_errors(error),
        )

    @api.exception_handler(LLMClientError)
    async def handle_llm_client_error(
        request: Request,
        error: LLMClientError,
    ) -> JSONResponse:
        if isinstance(error, LLMAuthenticationError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            message = "The live AI provider could not authenticate."
        elif isinstance(error, LLMConfigurationError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            message = "The live AI provider is not configured correctly."
        else:
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            message = "The live AI provider failed unexpectedly."

        log_event(
            "transport_error",
            level=logging.ERROR,
            request_id=request_id_from_request(request),
            error_code=error.error_code,
            error_type=type(error).__name__,
            status_code=status_code,
        )
        return _error_response(
            request,
            status_code=status_code,
            code=error.error_code,
            message=message,
        )

    @api.exception_handler(RagUnavailableError)
    async def handle_rag_unavailable_error(
        request: Request,
        error: RagUnavailableError,
    ) -> JSONResponse:
        log_event(
            "transport_error",
            level=logging.ERROR,
            request_id=request_id_from_request(request),
            error_code=error.error_code,
            error_type=type(error).__name__,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        return _error_response(
            request,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code=error.error_code,
            message="The required knowledge retrieval service is unavailable.",
        )

    @api.exception_handler(NotionCrmError)
    async def handle_notion_crm_error(
        request: Request,
        error: NotionCrmError,
    ) -> JSONResponse:
        if isinstance(error, NotionCrmNotConfiguredError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            message = "Notion CRM has not been configured."
        elif isinstance(error, NotionCrmUnavailableError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            message = "Notion CRM is temporarily unavailable."
        else:
            status_code = status.HTTP_502_BAD_GATEWAY
            message = "Notion CRM rejected the sync request."
        log_event(
            "transport_error",
            level=logging.ERROR,
            request_id=request_id_from_request(request),
            error_code=error.error_code,
            error_type=type(error).__name__,
            status_code=status_code,
        )
        return _error_response(
            request,
            status_code=status_code,
            code=error.error_code,
            message=message,
        )

    @api.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        log_event(
            "transport_error",
            level=logging.ERROR,
            request_id=request_id_from_request(request),
            error_code="internal_error",
            error_type=type(error).__name__,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return _error_response(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
            message="The service failed unexpectedly.",
        )
