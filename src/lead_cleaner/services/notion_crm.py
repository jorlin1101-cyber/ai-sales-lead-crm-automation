from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from time import sleep
from typing import Any

import httpx

from lead_cleaner.config import Settings
from lead_cleaner.schemas.crm import NotionCrmStatus, NotionSyncResponse
from lead_cleaner.schemas.lead import LeadProcessingResult


class NotionCrmError(RuntimeError):
    error_code = "notion_crm_error"


class NotionCrmNotConfiguredError(NotionCrmError):
    error_code = "notion_crm_not_configured"


class NotionCrmUnavailableError(NotionCrmError):
    error_code = "notion_crm_unavailable"

    def __init__(self, message: str, *, retry_after: float = 0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


PROPERTY_ALIASES: dict[str, tuple[str, ...]] = {
    "lead_id": ("Lead ID", "lead_id", "线索编号"),
    "email": ("Email", "email", "邮箱"),
    "company": ("Company", "company", "公司"),
    "source": ("Source", "source", "来源"),
    "intent": ("Intent", "intent_level", "意向等级"),
    "score": ("Score", "lead_score", "线索评分"),
    "disposition": ("Disposition", "disposition", "处置建议"),
    "needs_review": ("Needs Review", "needs_review", "需要复核"),
    "status": ("Status", "status", "状态"),
    "processed_at": ("Processed At", "processed_at", "处理时间"),
}


def create_notion_crm_writer(settings: Settings) -> NotionCrmWriter | None:
    if not settings.notion_crm_enabled:
        return None

    assert settings.notion_api_key is not None
    assert settings.notion_leads_data_source_id is not None
    return NotionCrmWriter(
        api_key=settings.notion_api_key.get_secret_value(),
        data_source_id=settings.notion_leads_data_source_id,
        api_version=settings.notion_api_version,
        timeout_seconds=settings.notion_timeout_seconds,
        max_retries=settings.notion_max_retries,
    )


class NotionCrmWriter:
    """Write a reviewed lead to a Notion data source without exposing credentials."""

    def __init__(
        self,
        *,
        api_key: str,
        data_source_id: str,
        api_version: str = "2025-09-03",
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        http_client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self.data_source_id = data_source_id.strip()
        self.max_retries = max_retries
        self._sleeper = sleeper
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            base_url="https://api.notion.com",
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Notion-Version": api_version,
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def status(self) -> NotionCrmStatus:
        data_source = self._request("GET", f"/v1/data_sources/{self.data_source_id}").json()
        title = _plain_text(data_source.get("title", [])) or None
        return NotionCrmStatus(
            configured=True,
            connected=True,
            workspace_name=None,
            data_source_title=title,
            message="Notion CRM 已连接，可以写入线索。",
        )

    def write(
        self,
        result: LeadProcessingResult,
        *,
        operator_name: str,
        approved_followup_email: str | None = None,
        update_existing: bool = False,
        sync_version: str | None = None,
    ) -> NotionSyncResponse:
        if not result.validation_result.is_valid or result.analysis_result is None:
            raise NotionCrmError("Only a valid, analyzed lead can be written to Notion.")

        schema = self._request("GET", f"/v1/data_sources/{self.data_source_id}").json()
        schema_properties = schema.get("properties", {})
        properties = _build_properties(result, schema_properties)
        if _resolve_property(schema_properties, "lead_id", "rich_text") is None:
            raise NotionCrmError("A Lead ID rich_text property is required for safe deduplication.")
        processed_at = datetime.now(UTC)
        existing_page = self._find_existing_page(
            result.cleaned_lead.lead_id,
            schema_properties,
        )
        if existing_page is not None:
            if update_existing:
                # Do not overwrite a salesperson's own CRM stage with 'New'.
                status_key = _resolve_property(schema_properties, "status", "select")
                if status_key:
                    properties.pop(status_key, None)
                self._request(
                    "PATCH", f"/v1/pages/{existing_page['id']}", json={"properties": properties}
                )
                children = _build_page_children(
                    result,
                    operator_name,
                    processed_at,
                    approved_followup_email=approved_followup_email,
                )
                if sync_version:
                    children.append(_paragraph("Sync Version", sync_version))
                self._request(
                    "PATCH",
                    f"/v1/blocks/{existing_page['id']}/children",
                    retry_safe=False,
                    json={"children": children},
                )
            return NotionSyncResponse(
                status="updated" if update_existing else "already_exists",
                lead_id=result.cleaned_lead.lead_id,
                page_id=existing_page["id"],
                page_url=existing_page.get("url"),
                synced_at=processed_at,
            )

        properties = _build_properties(result, schema_properties)
        payload: dict[str, Any] = {
            "parent": {"type": "data_source_id", "data_source_id": self.data_source_id},
            "properties": properties,
            "children": _build_page_children(
                result,
                operator_name,
                processed_at,
                approved_followup_email=approved_followup_email,
            ),
        }
        if sync_version:
            payload["children"].append(_paragraph("Sync Version", sync_version))
        page = self._request("POST", "/v1/pages", retry_safe=False, json=payload).json()
        return NotionSyncResponse(
            status="created",
            lead_id=result.cleaned_lead.lead_id,
            page_id=page["id"],
            page_url=page.get("url"),
            synced_at=processed_at,
        )

    def reconcile(self, lead_id: str, sync_version: str) -> NotionSyncResponse | None:
        schema = self._request("GET", f"/v1/data_sources/{self.data_source_id}").json()
        page = self._find_existing_page(lead_id, schema.get("properties", {}))
        if page is None:
            return None
        cursor = None
        for _ in range(20):
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            blocks = self._request("GET", f"/v1/blocks/{page['id']}/children", params=params).json()
            for block in blocks.get("results", []):
                rich = block.get("paragraph", {}).get("rich_text", [])
                text = "".join(
                    item.get("plain_text", item.get("text", {}).get("content", "")) for item in rich
                )
                if text == f"Sync Version: {sync_version}":
                    return NotionSyncResponse(
                        status="already_exists",
                        lead_id=lead_id,
                        page_id=page["id"],
                        page_url=page.get("url"),
                        synced_at=datetime.now(UTC),
                    )
            if not blocks.get("has_more"):
                break
            cursor = blocks["next_cursor"]
        return None

    def _find_existing_page(
        self,
        lead_id: str,
        schema_properties: dict[str, Any],
    ) -> dict[str, Any] | None:
        property_name = _resolve_property(schema_properties, "lead_id", "rich_text")
        if property_name is None:
            return None

        response = self._request(
            "POST",
            f"/v1/data_sources/{self.data_source_id}/query",
            json={
                "filter": {
                    "property": property_name,
                    "rich_text": {"equals": lead_id},
                },
                "page_size": 1,
            },
        ).json()
        results = response.get("results", [])
        return results[0] if results else None

    def _request(
        self,
        method: str,
        url: str,
        *,
        retry_safe: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        allowed_retries = self.max_retries if retry_safe else 0
        for attempt in range(allowed_retries + 1):
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.HTTPError as error:
                if attempt < allowed_retries:
                    self._sleeper(0.25 * (2**attempt))
                    continue
                raise NotionCrmUnavailableError("Notion could not be reached.") from error

            if response.status_code < 400:
                return response
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = max(0.0, float(retry_after)) if retry_after else 0.25 * (2**attempt)
                except ValueError:
                    delay = 0.25 * (2**attempt)
                if attempt < allowed_retries:
                    if delay > 5:
                        raise NotionCrmUnavailableError(
                            "Notion rate limited; retry after the scheduled delay.",
                            retry_after=delay,
                        )
                    self._sleeper(delay)
                    continue
                raise NotionCrmUnavailableError(
                    "Notion is temporarily unavailable.", retry_after=delay
                )
            if response.status_code in {401, 403}:
                raise NotionCrmError("Notion rejected the integration credentials or page access.")
            if response.status_code == 404:
                raise NotionCrmError("The configured Notion data source was not found.")
            raise NotionCrmError("Notion rejected the CRM record.")

        raise NotionCrmUnavailableError("Notion is temporarily unavailable.")


def _plain_text(items: list[dict[str, Any]]) -> str:
    return "".join(str(item.get("plain_text", "")) for item in items)


def _rich_text(value: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": value[:2000]}}]


def _resolve_property(
    properties: dict[str, Any],
    canonical_name: str,
    expected_type: str,
) -> str | None:
    for alias in PROPERTY_ALIASES[canonical_name]:
        prop = properties.get(alias)
        if prop and prop.get("type") == expected_type:
            return alias
    return None


def _build_properties(
    result: LeadProcessingResult,
    schema_properties: dict[str, Any],
) -> dict[str, Any]:
    analysis = result.analysis_result
    assert analysis is not None
    lead = result.cleaned_lead
    decision = analysis.decision
    title_name = next(
        (name for name, prop in schema_properties.items() if prop.get("type") == "title"),
        None,
    )
    if title_name is None:
        raise NotionCrmError("The Notion data source does not contain a title property.")

    values: dict[str, Any] = {
        title_name: {"title": _rich_text(lead.name or lead.company_name or lead.email)},
    }
    candidates = [
        ("lead_id", "rich_text", {"rich_text": _rich_text(lead.lead_id)}),
        ("email", "email", {"email": lead.email}),
        ("company", "rich_text", {"rich_text": _rich_text(lead.company_name)}),
        ("source", "select", {"select": {"name": lead.source[:100]}}),
        ("intent", "select", {"select": {"name": decision.intent_level}}),
        ("score", "number", {"number": decision.lead_score}),
        ("disposition", "select", {"select": {"name": decision.disposition}}),
        ("needs_review", "checkbox", {"checkbox": decision.needs_review}),
        ("status", "select", {"select": {"name": "New"}}),
        (
            "processed_at",
            "date",
            {"date": {"start": datetime.now(UTC).isoformat()}},
        ),
    ]
    for canonical_name, expected_type, value in candidates:
        property_name = _resolve_property(schema_properties, canonical_name, expected_type)
        if property_name:
            values[property_name] = value
    return values


def _paragraph(label: str, value: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {"type": "text", "text": {"content": f"{label}: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": value[:1900]}},
            ]
        },
    }


def _long_text_blocks(label: str, value: str) -> list[dict[str, Any]]:
    chunks = [value[index : index + 1800] for index in range(0, len(value), 1800)] or [""]
    blocks = [_paragraph(label, chunks[0])]
    blocks.extend(
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rich_text(chunk)},
        }
        for chunk in chunks[1:]
    )
    return blocks


def _heading(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": _rich_text(text)},
    }


def _build_page_children(
    result: LeadProcessingResult,
    operator_name: str,
    processed_at: datetime,
    *,
    approved_followup_email: str | None = None,
) -> list[dict[str, Any]]:
    analysis = result.analysis_result
    assert analysis is not None
    decision = analysis.decision
    score_lines = "; ".join(
        f"{item.component}: {item.points}/{item.max_points}" for item in decision.score_breakdown
    )
    source_lines = (
        "; ".join(f"{item.rank}. {item.source_title} — {item.section}" for item in result.sources)
        or "No knowledge source was used."
    )
    use_chinese = analysis.features.language == "zh"
    draft = (
        approved_followup_email.strip()
        if approved_followup_email and approved_followup_email.strip()
        else analysis.followup_email_draft
    )
    labels = (
        {
            "decision": "线索决策",
            "summary": "分析摘要",
            "action": "建议下一步",
            "score": "评分明细",
            "reasons": "复核原因",
            "none": "无",
            "original": "原始线索",
            "message": "客户留言",
            "source": "线索来源",
            "draft": "跟进邮件草稿",
            "email": "人工确认稿",
            "no_draft": "未生成邮件草稿。",
            "audit": "依据与审计",
            "knowledge": "知识来源",
            "no_source": "本次未使用知识库来源。",
            "policy": "策略版本",
            "confirmed_by": "确认人",
            "confirmed_at": "确认时间",
        }
        if use_chinese
        else {
            "decision": "Lead decision",
            "summary": "Summary",
            "action": "Recommended action",
            "score": "Score breakdown",
            "reasons": "Review reasons",
            "none": "None",
            "original": "Original lead",
            "message": "Message",
            "source": "Source",
            "draft": "Follow-up draft",
            "email": "Human-approved email",
            "no_draft": "No draft generated.",
            "audit": "Evidence and audit",
            "knowledge": "Knowledge sources",
            "no_source": "No knowledge source was used.",
            "policy": "Policy version",
            "confirmed_by": "Confirmed by",
            "confirmed_at": "Confirmed at",
        }
    )
    if not result.sources:
        source_lines = labels["no_source"]
    return [
        _heading(labels["decision"]),
        _paragraph(labels["summary"], analysis.lead_summary),
        _paragraph(labels["action"], analysis.recommended_action),
        _paragraph(labels["score"], score_lines),
        _paragraph(labels["reasons"], ", ".join(decision.review_reasons) or labels["none"]),
        _heading(labels["original"]),
        *_long_text_blocks(labels["message"], result.cleaned_lead.message),
        _paragraph(labels["source"], result.cleaned_lead.source),
        _heading(labels["draft"]),
        *_long_text_blocks(labels["email"], draft or labels["no_draft"]),
        _heading(labels["audit"]),
        _paragraph(labels["knowledge"], source_lines),
        _paragraph(labels["policy"], decision.policy_version),
        _paragraph(labels["confirmed_by"], operator_name),
        _paragraph(labels["confirmed_at"], processed_at.isoformat()),
    ]
