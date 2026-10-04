import copy
import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from lead_cleaner.evaluation.quality_context import (
    build_metadata,
    read_json,
    safe_relative,
    trusted_json,
    verify_protected_files,
)
from lead_cleaner.evaluation.quality_schema import (
    AssertionResult,
    CaseSpec,
    canonical_json,
    content_hash,
    expected_keys,
    result_key,
)


def case():
    return {
        "case_id": "F-test",
        "family": "fact",
        "language": "en",
        "adapter": "fact",
        "applicable_modes": ["mocked_model"],
        "payload": {},
        "assertions": [{"assertion_id": "value", "check": "equal"}],
    }


def result():
    return {
        "mode": "mocked_model",
        "case_id": "F-test",
        "probe_id": "main",
        "checkpoint": "result",
        "assertion_id": "value",
        "trial_id": "1",
        "execution_status": "completed",
        "behavior_status": "fail",
    }


def test_contract_rejects_unknown_fields_duplicates_and_invalid_state():
    sample = case()
    assert CaseSpec.model_validate(sample).review_status == "draft"
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
    assert content_hash({"x": 1}) != content_hash({"x": 2})
    assert result_key(result()) == ("mocked_model", "F-test", "main", "result", "value", "1")
    bad = copy.deepcopy(sample)
    bad["hidden_override"] = True
    with pytest.raises(ValidationError):
        CaseSpec.model_validate(bad)
    bad = copy.deepcopy(sample)
    bad["assertions"] *= 2
    with pytest.raises(ValidationError, match="duplicate assertion"):
        CaseSpec.model_validate(bad)
    bad = copy.deepcopy(sample)
    bad["applicable_modes"] *= 2
    with pytest.raises(ValidationError, match="duplicate applicable"):
        CaseSpec.model_validate(bad)
    assert AssertionResult.model_validate(result()).behavior_status == "fail"
    for update in [
        {"execution_status": "error"},
        {"behavior_status": None},
        {"behavior_status": "needs_review"},
    ]:
        with pytest.raises(ValidationError):
            AssertionResult.model_validate(result() | update)
    assert AssertionResult.model_validate(
        result() | {"behavior_status": "needs_review", "manual_review": True}
    )
    with pytest.raises(ValueError):
        canonical_json({"invalid": float("nan")})


def test_expected_keys_include_probe_and_trial_and_reject_collisions():
    sample = case()
    assert len(expected_keys([sample], "mocked_model", 3)) == 3
    assert expected_keys([sample], "rule_only") == []
    sample["assertions"][0]["applicable_modes"] = ["live"]
    assert expected_keys([sample], "mocked_model") == []
    with pytest.raises(ValueError):
        expected_keys([case(), case()], "mocked_model")
    for mode, trials in [("bad", 1), ("live", 0)]:
        with pytest.raises(ValueError):
            expected_keys([], mode, trials)


def init_repo(root: Path):
    root.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init")
    git("config", "user.email", "quality-test@example.invalid")
    git("config", "user.name", "Quality Test")
    (root / "config").mkdir()
    (root / "src").mkdir()
    (root / "src/score.py").write_text("value = 1\n", encoding="utf-8")
    protocol = {
        "protected_patterns": ["src/*.py", "config/*.json"],
        "s0_reference": "0" * 40,
        "protocol_id": "p0-test",
        "rubric_version": "v1",
    }
    (root / "config/quality_baseline.v1.json").write_text(json.dumps(protocol), encoding="utf-8")
    (root / "uv.lock").write_text("lock", encoding="utf-8")
    (root / "requirements.txt").write_text("example==1", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "test seed")
    return git("rev-parse", "HEAD"), protocol


def test_trusted_inputs_reject_changed_missing_and_added_grading_files(tmp_path):
    root = tmp_path / "repo"
    sha, protocol = init_repo(root)
    assert trusted_json(root, sha, "config/quality_baseline.v1.json") == protocol
    assert len(verify_protected_files(root, sha)["verified_files"]) == 2
    (root / "src/score.py").write_text("value = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="upgrade requires review"):
        verify_protected_files(root, sha)
    (root / "src/score.py").unlink()
    (root / "src/hidden.py").write_text("override = 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        verify_protected_files(root, sha)
    for unsafe in ["../x", "/tmp/x", "a\\b", "C:/x", "-x", "a//b", ""]:
        with pytest.raises(ValueError):
            safe_relative(unsafe)
    assert safe_relative("config/quality.json") == "config/quality.json"
    with pytest.raises(ValueError, match="full commit SHA"):
        trusted_json(root, "HEAD", "config/quality_baseline.v1.json")


def test_metadata_marks_unreviewed_or_dirty_work_as_provisional(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    sha, protocol = init_repo(root)
    # This unit test uses a tiny synthetic Git repository, not the imported app.
    # Isolate only its module inventory; production source verification stays strict.
    from types import SimpleNamespace
    from lead_cleaner.evaluation import quality_context

    monkeypatch.setattr(quality_context, "sys", SimpleNamespace(modules={}))
    metadata = build_metadata(root, [case()], "rule_only", protocol)
    assert metadata["tested_commit"] == sha
    assert metadata["provisional"] is True
    assert metadata["source_dirty"] is False
    assert metadata["live_status"] == "not_run"
    reviewed = case() | {"review_status": "reviewed"}
    clean = build_metadata(root, [reviewed], "live", protocol)
    assert clean["provisional"] is False
    (root / "src/score.py").write_text("value = 99\n", encoding="utf-8")
    dirty = build_metadata(root, [reviewed], "live", protocol)
    assert dirty["provisional"] and dirty["source_dirty"]
    assert clean["code_hash"] != dirty["code_hash"]
    assert clean["environment_hash"] == dirty["environment_hash"]
    assert read_json(root / "config/quality_baseline.v1.json") == protocol
    (root / "array.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        read_json(root / "array.json")
    subprocess.run(["git", "-C", str(root), "add", "array.json"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "array"], check=True, capture_output=True
    )
    sha2 = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    with pytest.raises(ValueError, match="not an object"):
        trusted_json(root, sha2, "array.json")


def test_reviewed_case_requires_identifiable_business_review():
    reviewed = case() | {"review_status": "reviewed"}
    with pytest.raises(ValidationError, match="review"):
        CaseSpec.model_validate(reviewed)
    audited = reviewed | {
        "reviewer": "business-test",
        "reviewed_at": "2026-10-04T00:00:00Z",
        "review_reason": "Test-only approval record",
    }
    assert CaseSpec.model_validate(audited).reviewer == "business-test"
