from pathlib import Path

import pytest
from pydantic import ValidationError

from lead_cleaner.config import AppMode, LLMProvider, RagBackend, Settings


@pytest.mark.parametrize(
    "app_mode",
    [
        AppMode.DEMO,
        AppMode.RULE_ONLY,
    ],
)
def test_offline_modes_do_not_require_provider_credentials(
    app_mode: AppMode,
) -> None:
    settings = Settings(
        _env_file=None,
        app_mode=app_mode,
        allow_network=False,
    )

    assert settings.app_mode == app_mode


def test_settings_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_mode="unknown",
            allow_network=False,
        )


def test_live_mode_requires_network() -> None:
    with pytest.raises(
        ValidationError,
        match="APP_MODE=live requires ALLOW_NETWORK=true",
    ):
        Settings(
            _env_file=None,
            app_mode=AppMode.LIVE,
            allow_network=False,
            llm_provider=LLMProvider.OPENAI,
            openai_api_key="test-key",
            openai_model="test-model",
        )


def test_live_openai_accepts_complete_configuration() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        allow_network=True,
        llm_provider=LLMProvider.OPENAI,
        openai_api_key="test-key",
        openai_model="test-model",
    )

    assert settings.llm_provider == LLMProvider.OPENAI
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "test-key"
    assert "test-key" not in repr(settings)


@pytest.mark.parametrize(
    ("provider_configuration", "missing_field"),
    [
        ({"openai_model": "test-model"}, "OPENAI_API_KEY"),
        ({"openai_api_key": "test-key"}, "OPENAI_MODEL"),
    ],
)
def test_live_openai_rejects_missing_configuration(
    provider_configuration: dict[str, str],
    missing_field: str,
) -> None:
    with pytest.raises(ValidationError, match=missing_field):
        Settings(
            _env_file=None,
            app_mode=AppMode.LIVE,
            allow_network=True,
            llm_provider=LLMProvider.OPENAI,
            **provider_configuration,
        )


def test_live_deepseek_accepts_complete_configuration() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        allow_network=True,
        llm_provider=LLMProvider.DEEPSEEK,
        deepseek_api_key="test-key",
        deepseek_model="test-model",
    )

    assert settings.llm_provider == LLMProvider.DEEPSEEK


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("llm_timeout_seconds", 0),
        ("llm_max_retries", -1),
    ],
)
def test_settings_rejects_invalid_reliability_values(
    field_name: str,
    invalid_value: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_mode=AppMode.DEMO,
            allow_network=False,
            **{field_name: invalid_value},
        )


def test_demo_fixture_path_can_be_configured_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "DEMO_FEATURE_FIXTURES_PATH",
        "custom/demo-fixtures.json",
    )

    settings = Settings(
        _env_file=None,
        app_mode=AppMode.DEMO,
        allow_network=False,
    )

    assert settings.demo_feature_fixtures_path == Path("custom/demo-fixtures.json")


def test_rag_defaults_to_offline_keyword_rrf() -> None:
    settings = Settings(_env_file=None)

    assert settings.rag_backend == RagBackend.KEYWORD_RRF
    assert settings.rag_required is False
    assert settings.rag_top_k == 3
    assert settings.rag_candidate_top_k == 5
    assert settings.knowledge_chunks_path == Path("data/knowledge_snapshot/knowledge_chunks.json")
    assert settings.bge_api_base_url == "http://127.0.0.1:8001/v1"
    assert settings.grounded_recommendation_enabled is False
    assert settings.recommendation_max_output_tokens == 1024


def test_required_rag_cannot_be_disabled() -> None:
    with pytest.raises(
        ValidationError,
        match="RAG_REQUIRED=true cannot be used with RAG_BACKEND=disabled",
    ):
        Settings(
            _env_file=None,
            rag_backend=RagBackend.DISABLED,
            rag_required=True,
        )


def test_bge_backend_requires_explicit_network_permission() -> None:
    with pytest.raises(
        ValidationError,
        match="RAG_BACKEND=bge_rrf requires ALLOW_NETWORK=true",
    ):
        Settings(
            _env_file=None,
            rag_backend=RagBackend.BGE_RRF,
            allow_network=False,
        )


def test_rag_candidate_count_must_cover_top_k() -> None:
    with pytest.raises(
        ValidationError,
        match="RAG_CANDIDATE_TOP_K must be greater than or equal to RAG_TOP_K",
    ):
        Settings(
            _env_file=None,
            rag_top_k=3,
            rag_candidate_top_k=2,
        )


def test_rag_paths_and_backend_can_be_configured_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("RAG_BACKEND", "disabled")
    monkeypatch.setenv("KNOWLEDGE_CHUNKS_PATH", "custom/chunks.json")

    settings = Settings(_env_file=None)

    assert settings.rag_backend == RagBackend.DISABLED
    assert settings.knowledge_chunks_path == Path("custom/chunks.json")


def test_grounded_recommendation_accepts_complete_live_openai_configuration() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        allow_network=True,
        llm_provider=LLMProvider.OPENAI,
        openai_api_key="test-key",
        openai_model="test-model",
        grounded_recommendation_enabled=True,
        recommendation_max_output_tokens=1200,
    )

    assert settings.grounded_recommendation_enabled is True
    assert settings.recommendation_max_output_tokens == 1200


def test_grounded_recommendation_requires_live_mode() -> None:
    with pytest.raises(ValidationError, match="requires APP_MODE=live"):
        Settings(
            _env_file=None,
            app_mode=AppMode.RULE_ONLY,
            allow_network=True,
            grounded_recommendation_enabled=True,
        )


def test_grounded_recommendation_requires_openai_provider() -> None:
    with pytest.raises(ValidationError, match="requires LLM_PROVIDER=openai"):
        Settings(
            _env_file=None,
            app_mode=AppMode.LIVE,
            allow_network=True,
            llm_provider=LLMProvider.DEEPSEEK,
            deepseek_api_key="test-key",
            deepseek_model="test-model",
            grounded_recommendation_enabled=True,
        )


def test_grounded_recommendation_requires_enabled_rag() -> None:
    with pytest.raises(ValidationError, match="non-disabled RAG_BACKEND"):
        Settings(
            _env_file=None,
            app_mode=AppMode.LIVE,
            allow_network=True,
            llm_provider=LLMProvider.OPENAI,
            openai_api_key="test-key",
            openai_model="test-model",
            rag_backend=RagBackend.DISABLED,
            grounded_recommendation_enabled=True,
        )


@pytest.mark.parametrize("max_output_tokens", [255, 2049])
def test_recommendation_token_limit_is_bounded(max_output_tokens: int) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            recommendation_max_output_tokens=max_output_tokens,
        )


def test_recommendation_settings_can_be_loaded_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "live")
    monkeypatch.setenv("ALLOW_NETWORK", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("GROUNDED_RECOMMENDATION_ENABLED", "true")
    monkeypatch.setenv("RECOMMENDATION_MAX_OUTPUT_TOKENS", "1400")

    settings = Settings(_env_file=None)

    assert settings.grounded_recommendation_enabled is True
    assert settings.recommendation_max_output_tokens == 1400
