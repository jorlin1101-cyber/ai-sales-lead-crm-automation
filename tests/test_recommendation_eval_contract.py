import json
from pathlib import Path

from lead_cleaner.evaluation.quality_checks import recommendation_contract_report


EVAL_PATH = Path("data/recommendation_eval/golden_cases.json")


def test_grounded_recommendation_eval_set_is_frozen_and_well_formed() -> None:
    payload = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    report = recommendation_contract_report(payload)
    assert report["kind"] == "data_contract"
    checks = [
        check for check in report["checks"] if not check["assertion_id"].startswith("boundary:")
    ]
    assert all(check["pass"] for check in checks), [check for check in checks if not check["pass"]]


def test_eval_set_contains_security_and_unsupported_claim_boundaries() -> None:
    payload = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    report = recommendation_contract_report(payload)
    checks = [check for check in report["checks"] if check["assertion_id"].startswith("boundary:")]
    assert len(checks) == 5
    assert all(check["pass"] for check in checks), [check for check in checks if not check["pass"]]
