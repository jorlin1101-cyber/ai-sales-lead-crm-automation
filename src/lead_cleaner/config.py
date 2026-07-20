from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppMode(StrEnum):
    DEMO = "demo"
    RULE_ONLY = "rule_only"
    LIVE = "live"


class LLMProvider(StrEnum):
    OPENAI = "openai"
    DEEPSEEK = "deepseek"


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
    demo_feature_fixtures_path: Path = Path("data/demo/lead_feature_fixtures.json")

    @model_validator(mode="after")
    def validate_live_configuration(self) -> Self:
        if self.app_mode != AppMode.LIVE:
            return self

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
                f"APP_MODE=live with LLM_PROVIDER={self.llm_provider.value} requires {missing_text}"
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
