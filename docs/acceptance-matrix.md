# Core Scenario Acceptance Matrix

This matrix maps public product claims to automated evidence without duplicating test implementation details.

| Scenario | Expected result | Automated evidence |
| --- | --- | --- |
| Health request | HTTP 200 with a unique request ID | `tests/test_api.py`; `tests/test_request_context.py` |
| Valid lead | Deterministic decision with policy metadata | `tests/test_api.py`; `tests/test_policy_v1.py` |
| Invalid lead | Domain-invalid response without analysis or RAG sources | `tests/test_api.py` |
| Prompt injection | Deterministic manual review; no grounded-generation claim | `tests/test_policy_v1.py`; `tests/test_recommendation_builder.py` |
| Offline modes | No provider client or external key is required | `tests/test_api_lifecycle.py`; `tests/test_network_policy.py` |
| Approved provider failure | Explicit rule fallback with a reason | `tests/test_live_feature_extractor.py` |
| RAG degradation | Optional failure preserves the decision; required failure returns 503 | `tests/test_api_rag_integration.py`; `tests/test_processor.py` |
| Grounded recommendation | Citations are limited to retrieved Top 3 chunks | `tests/test_openai_recommendation_generator.py`; `tests/test_rag_grounding.py` |
| Product and itinerary reply | Retrieved product facts appear in the channel-specific reply | `tests/test_conversation_eval.py`; `tests/test_conversations.py` |
| Pricing safety | Pricing rules are explained without inventing an unsupported amount | `tests/test_conversation_eval.py`; `tests/test_conversations.py` |
| Multi-turn context | A new message ID creates a new turn and carries confirmed facts forward | `tests/test_conversation_eval.py`; `tests/test_conversations.py` |
| Exact reply citations | Draft citations are a subset of the current retrieval evidence | `tests/test_conversation_eval.py`; `tests/test_conversations.py` |
| Docker deployment | Container builds, runs unprivileged, and becomes healthy | `tests/test_docker_deployment.py`; GitHub Actions Docker job |

Run the same local quality gate as CI:

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest -q
python scripts/ci_offline_smoke.py
```
