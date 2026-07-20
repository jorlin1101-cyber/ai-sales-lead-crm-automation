from pathlib import Path

import pytest
from pydantic import ValidationError

from lead_cleaner.config import AppMode, LLMProvider, Settings


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
