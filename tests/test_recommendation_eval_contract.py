import json
from pathlib import Path


EVAL_PATH = Path("data/recommendation_eval/golden_cases.json")


def test_grounded_recommendation_eval_set_is_frozen_and_well_formed() -> None:
    payload = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]

    assert payload["schema_version"] == "grounded-recommendation-eval-v1"
    assert len(cases) == 12
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert {"en", "zh", "mixed"} <= {case["language"] for case in cases}

    for case in cases:
        chunks = case["retrieved_chunks"]
        chunk_ids = [chunk["chunk_id"] for chunk in chunks]
        expected = case["expected"]

        assert case["case_id"].startswith("gr-")
        assert case["lead_message"].strip()
        assert 1 <= len(chunks) <= 3
        assert len(chunk_ids) == len(set(chunk_ids))
        assert all(chunk["text"].strip() for chunk in chunks)
        assert expected["required_behaviors"]
        assert expected["forbidden_behaviors"]
        assert set(expected["allowed_citation_ids"]) == set(chunk_ids)


def test_eval_set_contains_security_and_unsupported_claim_boundaries() -> None:
    payload = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    forbidden_behaviors = {
        behavior
        for case in payload["cases"]
        for behavior in case["expected"]["forbidden_behaviors"]
    }

    assert "follow_embedded_instruction" in forbidden_behaviors
    assert "cite_unknown_chunk" in forbidden_behaviors
    assert "invent_exact_price" in forbidden_behaviors
    assert "guarantee_availability" in forbidden_behaviors
    assert "claim_email_sent" in forbidden_behaviors
