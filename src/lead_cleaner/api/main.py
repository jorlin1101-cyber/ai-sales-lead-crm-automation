from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, cast

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse

from lead_cleaner.config import Settings
from lead_cleaner.rag.retriever import (
    CloseableRagRetriever,
    RagRetriever,
    RagUnavailableError,
)
from lead_cleaner.rag.retriever_factory import create_rag_retriever
from lead_cleaner.schemas.lead import LeadProcessingResult, RawLeadInput
from lead_cleaner.services.feature_extractor import (
    CloseableFeatureExtractor,
    FeatureExtractor,
)
from lead_cleaner.services.feature_extractor_factory import create_feature_extractor
from lead_cleaner.services.llm_errors import (
    LLMAuthenticationError,
    LLMClientError,
    LLMConfigurationError,
)
from lead_cleaner.services.processor import process_lead


def create_app(*, settings: Settings | None = None) -> FastAPI:
    """Build the API and own one feature extractor for its full lifetime."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_settings = settings or Settings()
        feature_extractor = create_feature_extractor(resolved_settings)
        rag_retriever: RagRetriever | None = None

        try:
            rag_retriever = create_rag_retriever(resolved_settings)

            app.state.settings = resolved_settings
            app.state.feature_extractor = feature_extractor
            app.state.rag_retriever = rag_retriever

            yield
        finally:
            if isinstance(rag_retriever, CloseableRagRetriever):
                rag_retriever.close()

            if isinstance(feature_extractor, CloseableFeatureExtractor):
                feature_extractor.close()

    api = FastAPI(
        title="AI Sales Lead Cleaner API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @api.exception_handler(LLMClientError)
    async def handle_llm_client_error(
        _request: Request,
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

        return JSONResponse(
            status_code=status_code,
            content={
                "detail": {
                    "code": error.error_code,
                    "message": message,
                }
            },
        )

    @api.exception_handler(RagUnavailableError)
    async def handle_rag_unavailable_error(
        _request: Request,
        _error: RagUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": {
                    "code": "rag_unavailable",
                    "message": "The required knowledge retrieval service is unavailable.",
                }
            },
        )

    def get_feature_extractor(request: Request) -> FeatureExtractor:
        return cast(FeatureExtractor, request.app.state.feature_extractor)

    def get_rag_retriever(request: Request) -> RagRetriever:
        return cast(RagRetriever, request.app.state.rag_retriever)

    @api.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @api.post("/process-lead", response_model=LeadProcessingResult)
    def process_lead_api(
        raw_lead: RawLeadInput,
        feature_extractor: Annotated[
            FeatureExtractor,
            Depends(get_feature_extractor),
        ],
        rag_retriever: Annotated[
            RagRetriever,
            Depends(get_rag_retriever),
        ],
    ) -> LeadProcessingResult:
        return process_lead(
            raw_lead,
            feature_extractor=feature_extractor,
            rag_retriever=rag_retriever,
        )

    return api


app = create_app()
