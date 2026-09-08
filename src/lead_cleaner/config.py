from enum import StrEnum
from pathlib import Path
from typing import Self, Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppMode(StrEnum):
    DEMO = "demo"
    RULE_ONLY = "rule_only"
    LIVE = "live"


class LLMProvider(StrEnum):
    OPENAI = "openai"
    DEEPSEEK = "deepseek"


class RagBackend(StrEnum):
    DISABLED = "disabled"
    KEYWORD_RRF = "keyword_rrf"
    BGE_RRF = "bge_rrf"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_mode: AppMode = AppMode.DEMO
    allow_network: bool = False

    llm_provider: LLMProvider = LLMProvider.OPENAI

    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    openai_base_url: str | None = None

    deepseek_api_key: SecretStr | None = None
    deepseek_model: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"

    llm_timeout_seconds: float = Field(default=20.0, gt=0)
    llm_max_retries: int = Field(default=1, ge=0)
    # Multi-turn Qwen uses a separate, explicit switch; public visitors stay offline.
    conversation_llm_enabled: bool = False
    dashscope_api_key: SecretStr | None = None
    dashscope_model: str = "qwen3.7-plus"
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    conversation_llm_timeout_seconds: float = Field(default=30.0, gt=0, le=60)
    demo_feature_fixtures_path: Path = Path("data/demo/lead_feature_fixtures.json")

    rag_backend: RagBackend = RagBackend.KEYWORD_RRF
    rag_required: bool = False
    rag_top_k: int = Field(default=3, ge=1, le=3)
    rag_candidate_top_k: int = Field(default=5, ge=1)
    knowledge_chunks_path: Path = Path("data/knowledge_snapshot/knowledge_chunks.json")
    bge_api_base_url: str = "http://127.0.0.1:8001/v1"
    bge_embedding_model: str = "BAAI/bge-m3"
    bge_timeout_seconds: float = Field(default=60.0, gt=0)

    grounded_recommendation_enabled: bool = False
    recommendation_max_output_tokens: int = Field(default=1024, ge=256, le=2048)

    notion_crm_enabled: bool = False
    notion_api_key: SecretStr | None = None
    notion_leads_data_source_id: str | None = None
    notion_api_version: str = "2025-09-03"
    notion_timeout_seconds: float = Field(default=15.0, gt=0)
    notion_max_retries: int = Field(default=2, ge=0, le=5)

    conversation_database_url: str | None = None
    conversation_auto_create_schema: bool = True
    # Local/CI compatibility only. PostgreSQL is configured through CONVERSATION_DATABASE_URL.
    # The v2 filename keeps an older prototype SQLite schema intact instead of rewriting it.
    conversation_db_path: Path = Path("data/runtime/conversations-v2.sqlite3")
    service_access_mode: Literal["local", "public_demo", "protected"] = "local"
    service_access_token: SecretStr | None = None
    service_session_secret: SecretStr | None = None
    pricing_rules_path: Path | None = None
    inbound_webhook_secret: SecretStr | None = None

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        if self.conversation_llm_enabled:
            if not self.allow_network:
                raise ValueError("CONVERSATION_LLM_ENABLED requires ALLOW_NETWORK=true")
            if not self.dashscope_api_key or not self.dashscope_api_key.get_secret_value().strip():
                raise ValueError("CONVERSATION_LLM_ENABLED requires DASHSCOPE_API_KEY")
            if not self.dashscope_model.strip():
                raise ValueError("DASHSCOPE_MODEL must not be empty")
            from urllib.parse import urlsplit

            endpoint = urlsplit(self.dashscope_base_url)
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
            ):
                raise ValueError(
                    "DASHSCOPE_BASE_URL requires an HTTPS endpoint without credentials"
                )
        if self.service_access_mode == "protected" and not self.service_access_token:
            raise ValueError("Protected access requires SERVICE_ACCESS_TOKEN.")
        if self.service_access_token and len(self.service_access_token.get_secret_value()) < 32:
            raise ValueError("SERVICE_ACCESS_TOKEN requires at least 32 characters.")
        if self.app_mode == AppMode.LIVE:
            if not self.allow_network:
                raise ValueError("APP_MODE=live requires ALLOW_NETWORK=true")

            if self.llm_provider == LLMProvider.OPENAI:
                missing_fields = self._find_missing_provider_fields(
                    api_key=self.openai_api_key,
                    model=self.openai_model,
                    api_key_name="OPENAI_API_KEY",
                    model_name="OPENAI_MODEL",
                )
            else:
                missing_fields = self._find_missing_provider_fields(
                    api_key=self.deepseek_api_key,
                    model=self.deepseek_model,
                    api_key_name="DEEPSEEK_API_KEY",
                    model_name="DEEPSEEK_MODEL",
                )

            if missing_fields:
                missing_text = ", ".join(missing_fields)
                raise ValueError(
                    "APP_MODE=live with "
                    f"LLM_PROVIDER={self.llm_provider.value} requires {missing_text}"
                )

        if self.rag_backend == RagBackend.DISABLED and self.rag_required:
            raise ValueError("RAG_REQUIRED=true cannot be used with RAG_BACKEND=disabled")

        if self.rag_backend == RagBackend.BGE_RRF and not self.allow_network:
            raise ValueError("RAG_BACKEND=bge_rrf requires ALLOW_NETWORK=true")

        if self.rag_candidate_top_k < self.rag_top_k:
            raise ValueError("RAG_CANDIDATE_TOP_K must be greater than or equal to RAG_TOP_K")

        if self.grounded_recommendation_enabled:
            if self.app_mode != AppMode.LIVE:
                raise ValueError("GROUNDED_RECOMMENDATION_ENABLED=true requires APP_MODE=live")

            if not self.allow_network:
                raise ValueError("GROUNDED_RECOMMENDATION_ENABLED=true requires ALLOW_NETWORK=true")

            if self.llm_provider != LLMProvider.OPENAI:
                raise ValueError("Grounded recommendation currently requires LLM_PROVIDER=openai")

            if self.rag_backend == RagBackend.DISABLED:
                raise ValueError("Grounded recommendation requires a non-disabled RAG_BACKEND")

        if self.notion_crm_enabled:
            if not self.allow_network:
                raise ValueError("NOTION_CRM_ENABLED=true requires ALLOW_NETWORK=true")

            missing_notion_fields: list[str] = []
            if self.notion_api_key is None or not self.notion_api_key.get_secret_value().strip():
                missing_notion_fields.append("NOTION_API_KEY")
            if (
                self.notion_leads_data_source_id is None
                or not self.notion_leads_data_source_id.strip()
            ):
                missing_notion_fields.append("NOTION_LEADS_DATA_SOURCE_ID")
            if missing_notion_fields:
                raise ValueError(
                    "NOTION_CRM_ENABLED=true requires " + ", ".join(missing_notion_fields)
                )

        return self

    @staticmethod
    def _find_missing_provider_fields(
        *,
        api_key: SecretStr | None,
        model: str | None,
        api_key_name: str,
        model_name: str,
    ) -> list[str]:
        missing_fields: list[str] = []

        if api_key is None or not api_key.get_secret_value().strip():
            missing_fields.append(api_key_name)

        if model is None or not model.strip():
            missing_fields.append(model_name)

        return missing_fields
