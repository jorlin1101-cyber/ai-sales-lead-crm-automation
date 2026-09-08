from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from lead_cleaner.config import AppMode, RagBackend, Settings
from lead_cleaner.schemas.lead import LeadProcessingResult
from lead_cleaner.services.notion_crm import (
    NotionCrmError,
    NotionCrmUnavailableError,
    NotionCrmWriter,
    create_notion_crm_writer,
)
from lead_cleaner.services.processor import process_lead


def _settings(**overrides: Any) -> Settings:
    values = {
        "_env_file": None,
        "app_mode": AppMode.RULE_ONLY,
        "allow_network": False,
        "rag_backend": RagBackend.DISABLED,
    }
    values.update(overrides)
    return Settings(**values)


def _result() -> LeadProcessingResult:
    from lead_cleaner.schemas.lead import RawLeadInput

    return process_lead(
        RawLeadInput(
            external_lead_id="web-001",
            name="Lina Chen",
            email="lina@example.com",
            company_name="Aurora Travel",
            message=(
                "We are a travel agency planning a private Sichuan tour for 28 clients. "
                "Please share availability and a quotation."
            ),
            source="Website",
        )
    )


def _schema(properties: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "title": [{"plain_text": "Sales Leads"}],
        "properties": properties
        or {
            "Lead": {"type": "title"},
            "线索编号": {"type": "rich_text"},
            "邮箱": {"type": "email"},
            "公司": {"type": "rich_text"},
            "来源": {"type": "select"},
            "意向等级": {"type": "select"},
            "线索评分": {"type": "number"},
            "处置建议": {"type": "select"},
            "需要复核": {"type": "checkbox"},
            "状态": {"type": "select"},
            "处理时间": {"type": "date"},
        },
    }


def _writer(handler, *, retries: int = 0, sleeper=lambda _: None) -> NotionCrmWriter:
    client = httpx.Client(
        base_url="https://api.notion.com",
        transport=httpx.MockTransport(handler),
    )
    return NotionCrmWriter(
        api_key="test-secret",
        data_source_id="data-source-1",
        max_retries=retries,
        http_client=client,
        sleeper=sleeper,
    )


def test_notion_configuration_is_opt_in_and_secret_is_not_required_by_default() -> None:
    assert create_notion_crm_writer(_settings()) is None


@pytest.mark.parametrize(
    "overrides, message",
    [
        (
            {"allow_network": False, "notion_api_key": "x", "notion_leads_data_source_id": "y"},
            "ALLOW_NETWORK",
        ),
        ({"allow_network": True, "notion_leads_data_source_id": "y"}, "NOTION_API_KEY"),
        ({"allow_network": True, "notion_api_key": "x"}, "NOTION_LEADS_DATA_SOURCE_ID"),
    ],
)
def test_enabled_notion_configuration_requires_safe_fields(overrides, message) -> None:
    with pytest.raises(ValueError, match=message):
        _settings(notion_crm_enabled=True, **overrides)


def test_writer_factory_builds_enabled_writer() -> None:
    writer = create_notion_crm_writer(
        _settings(
            notion_crm_enabled=True,
            allow_network=True,
            notion_api_key="test-secret",
            notion_leads_data_source_id="source-id",
        )
    )
    assert writer is not None
    assert writer.data_source_id == "source-id"
    writer.close()


def test_status_reports_connected_data_source() -> None:
    writer = _writer(lambda request: httpx.Response(200, json=_schema()))
    status = writer.status()
    assert status.configured is True
    assert status.connected is True
    assert status.data_source_title == "Sales Leads"


def test_write_supports_chinese_property_aliases_and_full_page_content() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=_schema())
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"results": []})
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"id": "page-001", "url": "https://notion.so/page-001"},
        )

    result = _result()
    response = _writer(handler).write(
        result,
        operator_name="Alice",
        approved_followup_email="Human-reviewed follow-up draft.",
    )

    assert response.status == "created"
    assert response.lead_id == result.cleaned_lead.lead_id
    assert response.page_url == "https://notion.so/page-001"
    assert captured["parent"] == {
        "type": "data_source_id",
        "data_source_id": "data-source-1",
    }
    properties = captured["properties"]
    assert properties["Lead"]["title"][0]["text"]["content"] == "Lina Chen"
    assert properties["邮箱"] == {"email": "lina@example.com"}
    assert properties["公司"]["rich_text"][0]["text"]["content"] == "Aurora Travel"
    assert properties["线索评分"]["number"] == result.analysis_result.decision.lead_score
    assert properties["状态"] == {"select": {"name": "New"}}
    body_text = json.dumps(captured["children"], ensure_ascii=False)
    assert "Recommended action" in body_text
    assert "Human-reviewed follow-up draft." in body_text
    assert "Alice" in body_text
    assert result.cleaned_lead.message in body_text


def test_write_requires_a_title_property() -> None:
    writer = _writer(
        lambda request: httpx.Response(200, json=_schema({"Email": {"type": "email"}}))
    )
    with pytest.raises(NotionCrmError, match="title property"):
        writer.write(_result(), operator_name="Alice")


def test_write_rejects_domain_invalid_lead() -> None:
    from lead_cleaner.schemas.lead import RawLeadInput

    invalid_result = process_lead(RawLeadInput(email="bad", message="hello"))
    writer = _writer(lambda request: pytest.fail("Notion must not be called"))
    with pytest.raises(NotionCrmError, match="valid, analyzed"):
        writer.write(invalid_result, operator_name="Alice")


def test_existing_lead_is_returned_without_creating_a_duplicate() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(200, json=_schema())
        if request.url.path.endswith("/query"):
            return httpx.Response(
                200,
                json={
                    "results": [{"id": "page-existing", "url": "https://notion.so/page-existing"}]
                },
            )
        return pytest.fail("An existing lead must not create another Notion page")

    response = _writer(handler).write(_result(), operator_name="Alice")

    assert response.status == "already_exists"
    assert response.page_id == "page-existing"
    assert calls == [
        "/v1/data_sources/data-source-1",
        "/v1/data_sources/data-source-1/query",
    ]


def test_page_creation_is_not_blindly_retried_after_uncertain_server_error() -> None:
    page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal page_calls
        if request.method == "GET":
            return httpx.Response(200, json=_schema())
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"results": []})
        page_calls += 1
        return httpx.Response(503)

    with pytest.raises(NotionCrmUnavailableError):
        _writer(handler, retries=2).write(_result(), operator_name="Alice")

    assert page_calls == 1


@pytest.mark.parametrize(
    "status_code, message",
    [
        (401, "credentials"),
        (403, "credentials"),
        (404, "not found"),
        (400, "rejected"),
    ],
)
def test_safe_non_retryable_notion_errors(status_code, message) -> None:
    writer = _writer(lambda request: httpx.Response(status_code, json={"secret": "hidden"}))
    with pytest.raises(NotionCrmError, match=message):
        writer.status()


def test_rate_limit_retries_and_honors_retry_after() -> None:
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0.01"})
        return httpx.Response(200, json=_schema())

    status = _writer(handler, retries=1, sleeper=delays.append).status()
    assert status.connected is True
    assert calls == 2
    assert delays == [0.01]


def test_server_error_exhausts_retries() -> None:
    writer = _writer(lambda request: httpx.Response(503), retries=1)
    with pytest.raises(NotionCrmUnavailableError, match="temporarily unavailable"):
        writer.status()


def test_network_error_retries_then_returns_safe_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("secret network detail", request=request)

    writer = _writer(handler, retries=1)
    with pytest.raises(NotionCrmUnavailableError, match="could not be reached") as error:
        writer.status()
    assert "secret network detail" not in str(error.value)
    assert calls == 2
