import json
import re
from pathlib import Path
from typing import Any


WORKFLOW_PATH = Path("n8n/ai-sales-lead-routing.json")
BRANCH_NODES = [
    "Prepare High Lead",
    "Prepare Medium Lead",
    "Prepare Low Lead",
    "Prepare Invalid Lead",
    "Prepare API Error",
]
DEMO_LEAD_IDS = [
    "n8n-demo-high-001",
    "n8n-demo-medium-001",
    "n8n-demo-low-001",
    "n8n-demo-invalid-001",
]


def _all_keys(value: Any):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _all_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _all_keys(nested)


def test_sanitized_n8n_workflow_has_five_explicit_routes() -> None:
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    nodes = workflow["nodes"]
    names = [node["name"] for node in nodes]
    ids = [node["id"] for node in nodes]

    assert workflow["active"] is False
    assert len(names) == len(set(names))
    assert len(ids) == len(set(ids))
    assert all(name in names for name in BRANCH_NODES)
    route_outputs = workflow["connections"]["Route Outcome"]["main"]
    assert [output[0]["node"] for output in route_outputs] == BRANCH_NODES

    route_node = next(node for node in nodes if node["name"] == "Route Outcome")
    route_rules = route_node["parameters"]["rules"]["values"]
    right_values = [rule["conditions"]["conditions"][0]["rightValue"] for rule in route_rules]
    assert right_values == ["high", "medium", "low", "invalid", "api_error"]


def test_n8n_workflow_calls_the_contract_without_embedding_credentials() -> None:
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    nodes = workflow["nodes"]
    node_names = {node["name"] for node in nodes}
    http_node = next(node for node in nodes if node["name"] == "Call FastAPI Process Lead")
    url = http_node["parameters"]["url"]

    assert http_node["parameters"]["method"] == "POST"
    assert url == "http://127.0.0.1:8000/process-lead"
    assert http_node["onError"] == "continueRegularOutput"
    assert set(workflow["connections"]).issubset(node_names)
    assert all(
        target["node"] in node_names
        for connection in workflow["connections"].values()
        for output in connection["main"]
        for target in output
    )
    assert "credentials" not in set(_all_keys(workflow))


def test_n8n_export_contains_only_safe_demo_data_and_no_policy_copy() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    emails = re.findall(r"(?i)[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})", text)

    assert emails
    assert set(domain.lower() for domain in emails) == {"example.com"}
    assert "C:\\Users\\" not in text
    assert "D:\\Python project\\" not in text
    assert not re.search(r"(?:sk-|ntn_|ghp_)[A-Za-z0-9_-]{12,}", text)
    assert "databaseId" not in text
    assert "customer_fit" not in text
    assert "intent_strength" not in text
    assert "order_value" not in text
    assert "information_completeness" not in text
    assert "Inspect API logs using the request ID." in text


def test_n8n_demo_lead_ids_are_canonical_and_unique() -> None:
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    sample_node = next(
        node for node in workflow["nodes"] if node["name"] == "Generate Safe Sample Leads"
    )
    sample_code = sample_node["parameters"]["jsCode"]
    lead_ids = re.findall(r"external_lead_id:\s*'([^']+)'", sample_code)

    assert lead_ids == DEMO_LEAD_IDS
    assert len(lead_ids) == len(set(lead_ids))
    assert all(lead_id == lead_id.strip() for lead_id in lead_ids)
