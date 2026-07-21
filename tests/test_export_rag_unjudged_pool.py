import json
from pathlib import Path

from lead_cleaner.rag.evaluation_report import sha256_file
from scripts.export_rag_unjudged_pool import export_unjudged_pool


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_export_unjudged_pool_includes_full_review_context(tmp_path: Path) -> None:
    eval_path = tmp_path / "eval.json"
    chunks_path = tmp_path / "chunks.json"
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "review.json"

    _write_json(
        eval_path,
        [
            {
                "query_id": "payment_001",
                "query": "Can the client pay a deposit first?",
                "language": "en",
                "query_type": "single_intent",
                "facets": [
                    {
                        "facet_id": "payment_schedule",
                        "description": "Whether deposit and balance payments are allowed.",
                    }
                ],
                "judgments": [
                    {
                        "source_title": "Payment FAQ",
                        "section": "Common Questions",
                        "relevance_grade": 3,
                        "covers_facets": ["payment_schedule"],
                        "reason": "Directly explains the payment schedule.",
                    }
                ],
            }
        ],
    )
    _write_json(
        chunks_path,
        [
            {
                "chunk_id": "chunk_direct",
                "source_type": "notion_page",
                "notion_page_id": "page_001",
                "source_title": "Payment FAQ",
                "source_path": "FAQ / Payment FAQ",
                "doc_type": "faq",
                "region": "general",
                "product_name": None,
                "section": "Common Questions",
                "chunk_index": 0,
                "chunk_strategy": "heading_section",
                "text": "A deposit can be paid before the final balance.",
                "last_edited_time": "2026-07-21T00:00:00Z",
            },
            {
                "chunk_id": "chunk_unjudged",
                "source_type": "notion_page",
                "notion_page_id": "page_001",
                "source_title": "Payment FAQ",
                "source_path": "FAQ / Payment FAQ",
                "doc_type": "faq",
                "region": "general",
                "product_name": None,
                "section": "Sales Notes",
                "chunk_index": 1,
                "chunk_strategy": "heading_section",
                "text": "Follow up with the agency after sending a quotation.",
                "last_edited_time": "2026-07-21T00:00:00Z",
            },
        ],
    )
    _write_json(
        report_path,
        {
            "report_schema_version": "rag-eval-v4",
            "label_contract_version": "paired-graded-relevance-v2",
            "dataset": {"sha256": sha256_file(eval_path)},
            "knowledge_snapshot": {"sha256": sha256_file(chunks_path)},
            "evaluations": {
                "runtime_fused_query": {
                    "cases": [
                        {
                            "query_id": "payment_001",
                            "retrieval_queries": [
                                "Can the client pay a deposit first?",
                                "payment policy deposit final balance",
                            ],
                            "retrieved_sources": [
                                {
                                    "chunk_id": "chunk_unjudged",
                                    "source_title": "Payment FAQ",
                                    "section": "Sales Notes",
                                    "rank": 1,
                                    "judged": False,
                                },
                                {
                                    "chunk_id": "chunk_direct",
                                    "source_title": "Payment FAQ",
                                    "section": "Common Questions",
                                    "rank": 2,
                                    "judged": True,
                                },
                            ],
                        }
                    ]
                }
            },
        },
    )

    payload = export_unjudged_pool(
        report_path=report_path,
        eval_path=eval_path,
        chunks_path=chunks_path,
        output_path=output_path,
    )

    assert payload["item_count"] == 1
    item = payload["items"][0]
    assert item["query_id"] == "payment_001"
    assert item["facets"][0]["facet_id"] == "payment_schedule"
    assert item["chunk_id"] == "chunk_unjudged"
    assert item["chunk_text"] == ("Follow up with the agency after sending a quotation.")
    assert item["review"] == {
        "relevance_grade": None,
        "covers_facets": [],
        "reason": "",
    }
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload
