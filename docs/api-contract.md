# Current API Contract

本文档只描述当前公开契约；历史决策由 ADR 和 Git 提交记录追溯。

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | 服务健康检查 |
| `POST` | `/process-lead` | 校验、清洗、分析、评分并检索知识来源 |

所有响应都会返回 `X-Request-ID`。调用方也可以主动发送这个 Header，用于串联
API、n8n 和 CRM 日志。

## Request

`POST /process-lead`

```json
{
  "external_lead_id": "n8n-demo-high-001",
  "name": "Demo High Lead",
  "email": "high@example.com",
  "company_name": "Example Travel Agency",
  "message": "Please quote a private Chengdu tour for 20 travelers in September.",
  "source": "website"
}
```

| Field | Type | Required | Rule |
| --- | --- | ---: | --- |
| `external_lead_id` | `string \| null` | No | 最长 100 |
| `name` | `string \| null` | No | 最长 200 |
| `email` | `string` | Yes | 最长 320；格式在业务校验阶段判断 |
| `company_name` | `string \| null` | No | 最长 300 |
| `message` | `string` | Yes | 1–5000 字符 |
| `source` | `string \| null` | No | 最长 100，空值清洗为 `Unknown` |

请求模型使用 `extra="forbid"`。例如发送旧字段 `company` 而不是
`company_name` 会得到 HTTP 422，不会被静默忽略。

## Success Response

HTTP 200 的顶层结构固定为：

```json
{
  "cleaned_lead": {},
  "validation_result": {
    "is_valid": true,
    "error_codes": []
  },
  "analysis_result": {},
  "sources": []
}
```

`analysis_result` 包含：

- `features`：受限业务特征；
- `security_signals`：确定性安全信号；
- `decision`：由 `PolicyV1` 生成的评分和处置结果；
- `lead_summary`、`recommended_action`、`followup_email_draft`；
- `metadata`：执行模式、分析方法、检索方法和 fallback 来源。

`metadata.recommendation_method` 只能是：

```text
llm_grounded | demo_template | generic_template | skipped
```

`llm_grounded` 只表示建议通过了结构化输出、引用白名单和安全门槛，不表示邮件已经发送。
该能力默认关闭，只对 qualified 且无需人工复核、有真实检索来源、无注入信号的线索启用。
任何推荐生成错误都会回落为 `generic_template`，不会修改 `decision`。
完整边界见 [Grounded recommendation](grounded-recommendation.md)。

其中两个容易误解的特征遵循以下契约：

- `features.language` 只能是 `en`、`zh`、`mixed` 或 `unknown`；
- `features.group_size` 只保存客户明确给出的精确人数；
- “至少 20 人”“10 到 20 人”“大约 20 人”等非精确表达返回 `null`，不会伪装成
  一个精确人数。

`decision.disposition` 只能是：

```text
qualified | nurture | spam | manual_review
```

`decision.intent_level` 只能是：

```text
High | Medium | Low
```

公开 `sources` 最多返回 3 条，并且只暴露：

```text
chunk_id | source_title | section | rank
```

知识正文、Notion page ID、内部路径和原始检索分数不会返回给调用方。

完整示例见 [API example](api-example.md)。

## Domain-invalid Lead

字段结构正确，但邮箱或消息不符合业务要求时，服务仍返回 HTTP 200：

```json
{
  "validation_result": {
    "is_valid": false,
    "error_codes": ["invalid_email_format"]
  },
  "analysis_result": null,
  "sources": []
}
```

当前业务错误码：

```text
empty_email
invalid_email_format
empty_message_after_cleaning
```

这是可记录的业务数据质量结果，不是 API 连接失败。

## Transport Errors

请求结构错误或服务无法安全完成处理时，返回非 2xx：

```json
{
  "detail": {
    "code": "request_validation_error",
    "message": "The request body does not match the API contract.",
    "request_id": "..."
  }
}
```

| HTTP status | Typical code | Meaning |
| ---: | --- | --- |
| 422 | `request_validation_error` | 缺字段、字段超长、未知字段或类型错误 |
| 503 | `llm_authentication_error` / `llm_configuration_error` | live provider 不可用 |
| 503 | `rag_unavailable` | 必需的 RAG 无法启动或检索 |
| 500 | `llm_client_error` / `internal_error` | 未批准 fallback 的运行时错误 |

安全错误响应不会回显 API Key、完整邮箱、客户消息或 provider 原始错误。

## Version Ownership

- 请求和响应 Schema：`src/lead_cleaner/schemas/`
- 确定性评分：`src/lead_cleaner/services/policy_v1.py`
- 错误映射：`src/lead_cleaner/api/error_handlers.py`
- 回归测试：`tests/test_api.py`、`tests/test_request_context.py`

改变公开字段时，必须同步修改 Schema、测试和本文档。
