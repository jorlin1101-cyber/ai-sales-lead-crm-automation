import json
from pathlib import Path

import pytest

from lead_cleaner.rag.evaluation_report import load_eval_cases, sha256_file
from scripts.merge_rag_judgment_review import merge_reviewed_judgments


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _eval_payload() -> list[dict[str, object]]:
    return [
        {
            "query_id": "payment_001",
            "query": "When is payment due?",
            "language": "en",
            "query_type": "single_intent",
            "facets": [
                {
                    "facet_id": "payment_schedule",
                    "description": "Explain when payment is due.",
                }
            ],
            "judgments": [
                {
                    "source_title": "Payment FAQ",
                    "section": "Payment Schedule",
                    "relevance_grade": 3,
                    "covers_facets": ["payment_schedule"],
                    "reason": "Directly answers the payment question.",
                }
            ],
        }
    ]


def _chunks_payload() -> list[dict[str, object]]:
    common = {
        "source_type": "notion_page",
        "notion_page_id": "page_001",
        "source_path": "FAQ / Payment FAQ",
        "doc_type": "faq",
        "region": "general",
        "product_name": None,
        "chunk_strategy": "heading_section",
        "last_edited_time": "2026-07-21T00:00:00Z",
    }
    return [
        {
            **common,
            "chunk_id": "chunk_direct",
            "source_title": "Payment FAQ",
            "section": "Payment Schedule",
            "chunk_index": 0,
            "text": "The deposit is due first and the balance is due before arrival.",
        },
        {
            **common,
            "chunk_id": "chunk_supporting",
            "source_title": "Payment FAQ",
            "section": "Sales Notes",
            "chunk_index": 1,
            "text": "Agency groups receive one invoice.",
        },
    ]


def _review_payload(*, eval_path: Path, chunks_path: Path) -> dict[str, object]:
    return {
        "review_schema_version": "rag-unjudged-review-v1",
        "label_contract_version": "paired-graded-relevance-v2",
        "dataset_sha256": sha256_file(eval_path),
        "knowledge_sha256": sha256_file(chunks_path),
        "item_count": 1,
        "items": [
            {
                "review_id": "payment_001::chunk_supporting",
                "query_id": "payment_001",
                "query": "When is payment due?",
                "facets": [
                    {
                        "facet_id": "payment_schedule",
                        "description": "Explain when payment is due.",
                    }
                ],
                "chunk_id": "chunk_supporting",
                "source_title": "Payment FAQ",
                "section": "Sales Notes",
                "chunk_text": "Agency groups receive one invoice.",
                "current_status": "reviewed",
                "review": {
                    "relevance_grade": 1,
                    "covers_facets": ["payment_schedule"],
                    "reason": "Related to payment but does not state the due dates.",
                },
            }
        ],
    }


def test_merge_reviewed_judgments_creates_a_valid_candidate(tmp_path: Path) -> None:
    eval_path = tmp_path / "eval.json"
    chunks_path = tmp_path / "chunks.json"
    review_path = tmp_path / "review.json"
    output_path = tmp_path / "candidate.json"
    _write_json(eval_path, _eval_payload())
    _write_json(chunks_path, _chunks_payload())
    _write_json(
        review_path,
        _review_payload(eval_path=eval_path, chunks_path=chunks_path),
    )

    summary = merge_reviewed_judgments(
        review_path=review_path,
        eval_path=eval_path,
        chunks_path=chunks_path,
        output_path=output_path,
    )

    assert summary["eval_case_count"] == 1
    assert summary["judgment_count_before"] == 1
    assert summary["reviewed_judgment_count"] == 1
    assert summary["judgment_count_after"] == 2
    assert summary["grade_counts"] == {"0": 0, "1": 1, "2": 0, "3": 0}
    merged = load_eval_cases(output_path)
    assert merged[0].judgments[1].section == "Sales Notes"
    assert merged[0].judgments[1].relevance_grade == 1


def test_merge_reviewed_judgments_rejects_a_stale_dataset(tmp_path: Path) -> None:
    eval_path = tmp_path / "eval.json"
    chunks_path = tmp_path / "chunks.json"
    review_path = tmp_path / "review.json"
    output_path = tmp_path / "candidate.json"
    _write_json(eval_path, _eval_payload())
    _write_json(chunks_path, _chunks_payload())
    review = _review_payload(eval_path=eval_path, chunks_path=chunks_path)
    review["dataset_sha256"] = "0" * 64
    _write_json(review_path, review)

    with pytest.raises(ValueError, match="changed after the review pool"):
        merge_reviewed_judgments(
            review_path=review_path,
            eval_path=eval_path,
            chunks_path=chunks_path,
            output_path=output_path,
        )


def test_merge_reviewed_judgments_rejects_an_existing_pair(tmp_path: Path) -> None:
    eval_path = tmp_path / "eval.json"
    chunks_path = tmp_path / "chunks.json"
    review_path = tmp_path / "review.json"
    output_path = tmp_path / "candidate.json"
    eval_payload = _eval_payload()
    existing = dict(eval_payload[0]["judgments"][0])
    existing.update(
        {
            "section": "Sales Notes",
            "relevance_grade": 1,
            "reason": "Already labeled.",
        }
    )
    eval_payload[0]["judgments"].append(existing)
    _write_json(eval_path, eval_payload)
    _write_json(chunks_path, _chunks_payload())
    _write_json(
        review_path,
        _review_payload(eval_path=eval_path, chunks_path=chunks_path),
    )

    with pytest.raises(ValueError, match="Judgment already exists"):
        merge_reviewed_judgments(
            review_path=review_path,
            eval_path=eval_path,
            chunks_path=chunks_path,
            output_path=output_path,
        )
