from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_required_docker_files_exist() -> None:
    required_files = (
        "Dockerfile",
        "compose.yaml",
        ".dockerignore",
        ".env.example",
    )

    for file_name in required_files:
        assert (PROJECT_ROOT / file_name).is_file()


def test_dockerfile_has_safe_runtime_settings() -> None:
    dockerfile = read_project_file("Dockerfile")

    assert "FROM python:3.12-slim" in dockerfile
    assert "USER app" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert '"lead_cleaner.api.main:app"' in dockerfile
    assert "COPY . ." not in dockerfile


def test_compose_has_expected_api_settings() -> None:
    compose = read_project_file("compose.yaml")

    assert "127.0.0.1:${API_PORT:-8000}:8000" in compose
    assert "env_file:" in compose
    assert "restart: unless-stopped" in compose
    assert "init: true" in compose


def test_dockerignore_excludes_private_and_development_files() -> None:
    ignored_lines = {
        line.strip()
        for line in read_project_file(".dockerignore").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert ".env" in ignored_lines
    assert ".venv" in ignored_lines
    assert "tests" in ignored_lines
    assert "docs" in ignored_lines
    assert "!.env.example" in ignored_lines


def test_env_example_documents_docker_port() -> None:
    env_example = read_project_file(".env.example")

    assert "API_PORT=8000" in env_example
