"""Reject reports that label one checkout while executing another installation."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from lead_cleaner.evaluation import quality_context as context


@pytest.fixture
def source_repository(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    package = root / "src/lead_cleaner"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# synthetic package\n", encoding="utf-8")
    (package / "business.py").write_text("value = 1\n", encoding="utf-8")
    nested = package / "services"
    nested.mkdir()
    (nested / "__init__.py").write_text("# synthetic nested package\n", encoding="utf-8")
    (root / "uv.lock").write_text("synthetic-lock", encoding="utf-8")
    (root / "requirements.txt").write_text("synthetic==1", encoding="utf-8")
    modules = {
        "lead_cleaner": SimpleNamespace(
            __file__=str(package / "__init__.py"), __path__=[str(package)]
        ),
        "lead_cleaner.business": SimpleNamespace(__file__=str(package / "business.py")),
        "lead_cleaner.services": SimpleNamespace(
            __file__=str(nested / "__init__.py"), __path__=[str(nested)]
        ),
        "unrelated.package": SimpleNamespace(__file__="external-library.py"),
    }
    monkeypatch.setattr(context, "sys", SimpleNamespace(modules=modules))
    monkeypatch.setattr(
        context, "git", lambda root, *args: "a" * 40 if args[0] == "rev-parse" else ""
    )
    protocol = {"s0_reference": "b" * 40, "protocol_id": "test", "rubric_version": "test"}
    return root, modules, protocol


def metadata(fixture):
    root, _, protocol = fixture
    return context.build_metadata(root, [{"review_status": "draft"}], "rule_only", protocol)


def test_package_and_module_paths_are_verified_and_fingerprinted(source_repository):
    root, _, _ = source_repository
    loaded = metadata(source_repository)["loaded_modules"]
    assert set(loaded) == {"lead_cleaner", "lead_cleaner.business", "lead_cleaner.services"}
    assert loaded["lead_cleaner"]["path"] == str((root / "src/lead_cleaner/__init__.py").resolve())
    assert loaded["lead_cleaner.services"]["path"] == str(
        (root / "src/lead_cleaner/services/__init__.py").resolve()
    )
    business = root / "src/lead_cleaner/business.py"
    assert loaded["lead_cleaner.business"]["sha256"] == context.sha256_file(business)


def test_another_installation_is_rejected_even_if_source_bytes_match(source_repository, tmp_path):
    root, modules, _ = source_repository
    other = tmp_path / "other-installation/lead_cleaner/business.py"
    other.parent.mkdir(parents=True)
    other.write_bytes((root / "src/lead_cleaner/business.py").read_bytes())
    modules["lead_cleaner.business"].__file__ = str(other)
    with pytest.raises(ValueError, match="source differs.*lead_cleaner.business"):
        metadata(source_repository)


def test_different_module_file_inside_same_checkout_is_rejected(source_repository):
    root, modules, _ = source_repository
    wrong = root / "src/lead_cleaner/other.py"
    wrong.write_text("value = 1\n", encoding="utf-8")
    modules["lead_cleaner.business"].__file__ = str(wrong)
    with pytest.raises(ValueError, match="source differs"):
        metadata(source_repository)


def test_root_package_from_another_installation_is_not_skipped(source_repository, tmp_path):
    _, modules, _ = source_repository
    package = tmp_path / "other-package/__init__.py"
    package.parent.mkdir()
    package.write_text("", encoding="utf-8")
    modules["lead_cleaner"].__file__ = str(package)
    with pytest.raises(ValueError, match="source differs.*lead_cleaner"):
        metadata(source_repository)


@pytest.mark.parametrize("filename", [None, "opaque-extension.pyd", "cached-module.pyc"])
def test_unverifiable_loaded_sources_are_rejected(source_repository, filename):
    _, modules, _ = source_repository
    modules["lead_cleaner.business"].__file__ = filename
    with pytest.raises(ValueError, match="no verifiable Python source"):
        metadata(source_repository)


def test_missing_expected_source_cannot_be_reported_as_current_code(source_repository):
    root, _, _ = source_repository
    (root / "src/lead_cleaner/business.py").unlink()
    with pytest.raises(ValueError, match="source differs"):
        metadata(source_repository)


def test_second_snapshot_checks_newly_loaded_dynamic_modules(source_repository, tmp_path):
    _, modules, _ = source_repository
    first = metadata(source_repository)
    assert "lead_cleaner.services.late" not in first["loaded_modules"]
    other = tmp_path / "late.py"
    other.write_text("value = 'outside'\n", encoding="utf-8")
    modules["lead_cleaner.services.late"] = SimpleNamespace(__file__=str(other))
    with pytest.raises(ValueError, match="source differs.*lead_cleaner.services.late"):
        metadata(source_repository)


def test_valid_dynamic_module_appears_in_second_verified_snapshot(source_repository):
    root, modules, _ = source_repository
    metadata(source_repository)
    later = root / "src/lead_cleaner/services/late.py"
    later.write_text("value = 'inside'\n", encoding="utf-8")
    modules["lead_cleaner.services.late"] = SimpleNamespace(__file__=str(later))
    second = metadata(source_repository)
    assert second["loaded_modules"]["lead_cleaner.services.late"]["sha256"] == context.sha256_file(
        later
    )


def test_hash_change_during_loaded_source_verification_is_rejected(source_repository, monkeypatch):
    original = context.sha256_file
    calls = 0

    def changing_hash(path):
        nonlocal calls
        if path.name == "business.py":
            calls += 1
            return "first" if calls == 1 else "changed"
        return original(path)

    monkeypatch.setattr(context, "sha256_file", changing_hash)
    with pytest.raises(ValueError, match="changed during verification"):
        metadata(source_repository)


def test_actual_editable_checkout_has_no_foreign_loaded_modules():
    root = Path(__file__).resolve().parents[1]
    protocol = context.read_json(root / "config/quality_baseline.v1.json")
    observed = context.build_metadata(root, [{"review_status": "draft"}], "rule_only", protocol)
    assert "lead_cleaner" in observed["loaded_modules"]
    assert "lead_cleaner.evaluation.quality_context" in observed["loaded_modules"]
    assert all(
        Path(item["path"]).is_relative_to(root / "src")
        for item in observed["loaded_modules"].values()
    )


def test_retrieval_labels_affect_input_fingerprint_and_dirty_scope(source_repository, monkeypatch):
    root, _, _ = source_repository
    before = metadata(source_repository)
    labels = root / "data/rag_eval/eval_queries.json"
    labels.parent.mkdir(parents=True)
    labels.write_text('{"queries": []}', encoding="utf-8")
    calls = []

    def git(root, *args):
        calls.append(args)
        return "a" * 40 if args[0] == "rev-parse" else "?? data/rag_eval/eval_queries.json"

    monkeypatch.setattr(context, "git", git)
    after = metadata(source_repository)
    assert after["source_dirty"] is True
    assert after["evaluation_data_hash"] != before["evaluation_data_hash"]
    assert "data/rag_eval" in next(args for args in calls if args[0] == "status")
