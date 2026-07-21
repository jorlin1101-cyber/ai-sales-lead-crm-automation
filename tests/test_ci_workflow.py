from pathlib import Path

import yaml


CI_PATH = Path(".github/workflows/ci.yml")


def test_ci_workflow_is_an_offline_python_312_quality_gate() -> None:
    text = CI_PATH.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    quality = workflow["jobs"]["quality"]
    env = quality["env"]
    steps = quality["steps"]
    step_text = "\n".join(str(step) for step in steps)

    assert workflow["permissions"] == {"contents": "read"}
    assert quality["runs-on"] == "ubuntu-latest"
    assert env["APP_MODE"] == "demo"
    assert env["ALLOW_NETWORK"] == "false"
    assert env["RAG_BACKEND"] == "keyword_rrf"
    assert env["RAG_REQUIRED"] == "true"
    assert env["OPENAI_API_KEY"] == ""
    assert env["DEEPSEEK_API_KEY"] == ""
    assert env["NOTION_API_KEY"] == ""
    assert "actions/checkout@v6" in step_text
    assert "actions/setup-python@v6" in step_text
    assert "'python-version': '3.12'" in step_text
    assert "python -m ruff check ." in step_text
    assert "python -m ruff format --check ." in step_text
    assert "python -m mypy src" in step_text
    assert "python -m pytest -q" in step_text
    assert "python scripts/ci_offline_smoke.py" in step_text
    assert "${{ secrets." not in text
