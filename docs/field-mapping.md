# Field Mapping

## 1. 目的

本文档用于说明 Leads Table 和 Processing Log Table 中每个字段是如何产生、转换和映射的。

本项目的数据会经过以下几个阶段：

1. Python 读取和清洗原始 lead JSON。
2. Python 执行基础字段校验。
3. LLM 或规则提取受限业务特征；SecuritySignalDetector 生成复核信号；PolicyV1 生成最终决策。
4. n8n 负责流程编排、CRM 写入和通知。
5. Notion / Airtable CRM 保存结构化结果。
6. 人工审核高价值或高风险 lead。

本文件的作用是避免字段来源混乱。每个字段都必须回答三个问题：

1. 这个字段从哪里来？
2. 这个字段在哪一步产生？
3. 这个字段要如何写入 CRM？

## 2. Lead Field Mapping

| CRM Field             | Source Step            | Source Field                            | Transformation Rule                                               | Required |
| --------------------- | ---------------------- | --------------------------------------- | ----------------------------------------------------------------- | -------- |
| `lead_id`             | Python / System        | `cleaned_lead.lead_id`                  | 由服务端生成，用于追踪 lead                                      | Yes      |
| `external_lead_id`    | Raw Lead JSON          | `cleaned_lead.external_lead_id`         | 原样保留外部标识；当前不把它声明为唯一键或幂等保证                | No       |
| `name`                | Raw Lead JSON          | `cleaned_lead.name`                     | 去除前后空格；缺失时保存空字符串                                  | No       |
| `email`               | Raw Lead JSON          | `cleaned_lead.email`                    | 去除前后空格并转换为小写；业务 invalid 时允许为空                 | No       |
| `company_name`        | Raw Lead JSON / Adapter| `cleaned_lead.company_name`             | 只接收标准字段；不得由 AI 从 message 猜测                          | No       |
| `message`             | Raw Lead JSON          | `cleaned_lead.message`                  | 去除前后空格，保留客户表达                                        | Yes      |
| `source`              | Raw Lead JSON          | `cleaned_lead.source`                   | 缺失、null、空字符串或纯空白时设置为 `Unknown`                    | Yes      |
| `is_valid`            | Python Validation      | `validation_result.is_valid`            | 保存业务验证结果 Boolean                                         | Yes      |
| `error_codes`         | Python Validation      | `validation_result.error_codes`         | 保存零个或多个机器可读错误码；有效 lead 必须为空列表              | Yes      |
| `lead_type`           | PolicyV1               | `analysis_result.decision.lead_type`             | valid lead 才有值；必须为 `B2B`、`B2C` 或 `Unknown`               | No       |
| `lead_subtype`        | PolicyV1               | `analysis_result.decision.lead_subtype`          | valid lead 才有值；必须匹配当前 API 枚举                           | No       |
| `intent_level`        | PolicyV1               | `analysis_result.decision.intent_level`          | valid lead 才有值；必须为 `High`、`Medium` 或 `Low`                | No       |
| `lead_score`          | PolicyV1               | `analysis_result.decision.lead_score`            | valid lead 才有值；整数必须在 0～100 之间                          | No       |
| `disposition`         | PolicyV1               | `analysis_result.decision.disposition`           | `qualified`、`nurture`、`spam` 或 `manual_review`                  | No       |
| `needs_review`        | PolicyV1               | `analysis_result.decision.needs_review`          | 是否需要人工复核                                                   | No       |
| `review_reasons`      | PolicyV1               | `analysis_result.decision.review_reasons`        | 服务端机器可读复核原因                                             | No       |
| `policy_version`      | PolicyV1               | `analysis_result.decision.policy_version`        | 当前固定为 `policy-v1`                                             | No       |
| `lead_summary`        | Current Analysis       | `analysis_result.lead_summary`          | valid lead 的简短总结                                             | No       |
| `recommended_action`  | Current Analysis       | `analysis_result.recommended_action`    | valid lead 的建议动作                                             | No       |
| `followup_email_draft`| Current Analysis       | `analysis_result.followup_email_draft`  | 只作为邮件草稿供人工审核，不自动发送                              | No       |
| `analysis_method`     | Python / System        | `analysis_result.metadata.analysis_method`       | 当前为 `llm_features` 或 `rule_features`                           | No       |
| `fallback_reason`     | Python / System        | `analysis_result.metadata.fallback_reason`       | 未降级时为空；降级时保存服务端原因码                               | No       |
| `sources`             | API / RAG              | `sources`                               | 保存脱敏 Top 1～3 来源；domain-invalid 或未检索时为空             | No       |
| `ai_analysis_status`  | n8n / System           | API processing result                   | valid 分析成功后为 `Completed`；invalid 为 `Skipped`              | Yes      |
| `crm_status`          | n8n / System           | CRM write result                        | 根据 CRM 写入结果设置状态                                         | Yes      |
| `notification_status` | n8n / System           | notification result                     | 根据通知结果设置为 `Sent`、`Failed` 或 `Not Required`             | No       |
| `review_status`       | Human / System         | review result                           | 默认设置为 `Pending Review`                                       | Yes      |
| `received_at`         | Raw Lead JSON / System | `received_at` or current time           | 使用原始创建时间；没有则使用系统当前时间                           | No       |
| `processed_at`        | System                 | current time                            | 使用系统处理完成时间                                               | No       |

### 2.1 外部字段适配规则

FastAPI 只接受 `company_name`。如果旧表单或旧工作流发送 `company`，n8n 必须在 HTTP Request 节点之前明确转换：

```text
company → company_name
删除 company
```

不得同时保留 `company` 并依赖 API 静默忽略，因为 `RawLeadInput` 已设置 `extra="forbid"`，这种请求会返回 HTTP 422。

### 2.2 invalid lead 映射规则

当 `validation_result.is_valid=false` 时：

- `error_codes` 至少包含一个错误码；
- `analysis_result` 为 `null`；
- `sources` 为空列表；
- n8n 不得读取或伪造 `lead_type`、`lead_score` 等分析字段。

## 3. Processing Log Field Mapping

| CRM Field         | Source Step  | Source Field       | Transformation Rule                     | Required |
| ----------------- | ------------ | ------------------ | --------------------------------------- | -------- |
| `log_id`          | System       | generated          | 生成唯一 log ID                         | Yes      |
| `lead_id`         | Python / CRM | `lead_id`          | 关联对应 lead 记录                      | Yes      |
| `workflow_run_id` | n8n          | execution ID       | 保存 n8n workflow 执行 ID               | Yes      |
| `step_name`       | n8n / System | current node name  | 必须匹配 Select Options                 | Yes      |
| `status`          | n8n / System | step result        | 设置为 `Success`、`Failed` 或 `Skipped` | Yes      |
| `error_message`   | n8n / System | error details      | 成功时为空；失败时记录错误详情          | No       |
| `fallback_reason` | Python / System | analysis metadata | 只保存服务端原因码，不保存完整 provider response | No       |
| `received_at`     | System       | current time       | 日志创建时间                            | Yes      |
