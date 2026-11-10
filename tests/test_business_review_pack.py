from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/business_review_pack.py"
spec = importlib.util.spec_from_file_location("business_review_pack", SCRIPT)
assert spec and spec.loader
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)


def test_review_pending_disagreements_and_failure_queue(tmp_path):
    row = {
        "case_id": "A",
        "turn_id": "1",
        "group": "handbook",
        "mode": "rule_only",
        "evidence_id": "e",
    }
    first = {
        "evidence_id": "e",
        "dimension": "grounding",
        "reviewer": "a",
        "grade": "pass",
        "reason": "Supported",
    }
    second = {
        **first,
        "reviewer": "b",
        "grade": "partial",
        "reason": "Missing term",
        "cause": "missing_context",
    }
    decisions, queue = pack.adjudicate([row], [first, second])
    assert [d["status"] for d in decisions] == ["pending", "disagreement", "pending"]
    assert len(queue) == 3
    resolution = {**second, "reviewer": "arbiter", "reviewed_opinions": ["a", "b"]}
    result, _ = pack.adjudicate([row], [first, second], [resolution])
    assert result[1]["status"] == "partial" and result[1]["ratings"] == [first, second]
    with pytest.raises(ValueError):
        pack.adjudicate([row], [first, second], [{**resolution, "reviewed_opinions": ["a"]}])
    pack.render(tmp_path, [row], decisions, queue, {})
    assert "missing_context" in (tmp_path / "report.md").read_text()
    for bad in ([first, first], [{**first, "evidence_id": "new"}], [{**first, "reason": ""}]):
        with pytest.raises(ValueError):
            pack.adjudicate([row], bad)
