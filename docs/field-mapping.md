# Field Mapping

## 1. 目的

本文档用于说明 Leads Table 和 Processing Log Table 中每个字段是如何产生、转换和映射的。

本项目的数据会经过以下几个阶段：

1. Python 读取和清洗原始 lead JSON。
2. Python 执行基础字段校验。
3. AI 进行 lead 类型判断、意向判断、评分、摘要和邮件草稿生成。
4. n8n 负责流程编排、CRM 写入和通知。
5. Notion / Airtable CRM 保存结构化结果。
6. 人工审核高价值或高风险 lead。

本文件的作用是避免字段来源混乱。每个字段都必须回答三个问题：

1. 这个字段从哪里来？
2. 这个字段在哪一步产生？
3. 这个字段要如何写入 CRM？

## 2. Lead Field Mapping

| CRM Field             | Source Step            | Source Field                              | Transformation Rule                                      | Required |
| --------------------- | ---------------------- | ----------------------------------------- | -------------------------------------------------------- | -------- |
| `lead_id`             | Python / System        | generated                                 | 生成唯一 ID，用于追踪 lead                               | Yes      |
| `name`                | Raw Lead JSON          | `name`                                    | 去除前后空格                                             | Yes      |
| `email`               | Raw Lead JSON          | `email`                                   | 去除前后空格，并转换为小写                               | Yes      |
| `company_name`        | Raw Lead JSON / AI     | `company_name` or inferred from `message` | 可选字段；未知时留空                                     | No       |
| `message`             | Raw Lead JSON          | `message`                                 | 去除前后空格，保留客户原始表达                           | Yes      |
| `source`              | Raw Lead JSON          | `source`                                  | 缺失时设置为 `Unknown`                                   | Yes      |
| `is_valid`            | Python Validation      | validation result                         | 根据必填字段是否完整生成 Boolean 值                      | Yes      |
| `error_reason`        | Python Validation      | validation error                          | 有效 lead 为空；无效 lead 记录失败原因                   | No       |
| `lead_type`           | AI Analysis            | `lead_type`                               | 必须匹配 Select Options，例如 `B2B` / `B2C` / `Unknown`  | No       |
| `b2b_category`        | AI Analysis            | `b2b_category`                            | 必须匹配 Select Options                                  | No       |
| `intent_level`        | AI Analysis            | `intent_level`                            | 必须匹配 Select Options，例如 `High` / `Medium` / `Low`  | No       |
| `lead_score`          | AI Analysis            | `lead_score`                              | 数值必须在 0-100 之间                                    | No       |
| `lead_summary`        | AI Analysis            | `lead_summary`                            | 长文本，简短总结 lead 内容                               | No       |
| `recommended_action`  | AI Analysis            | `recommended_action`                      | 长文本，说明建议下一步动作                               | No       |
| `follow_up_email`     | AI Analysis            | `follow_up_email`                         | 长文本，只作为邮件草稿，不自动发送                       | No       |
| `ai_analysis_status`  | n8n / System           | AI node result                            | 根据 AI 节点结果设置为 `Success`、`Failed` 或 `Skipped`  | Yes      |
| `crm_status`          | n8n / System           | CRM write result                          | 根据 CRM 写入结果设置为 `Success`、`Failed` 或 `Skipped` | Yes      |
| `notification_status` | n8n / System           | notification result                       | 根据通知结果设置为 `Sent`、`Failed` 或 `Not Required`    | No       |
| `review_status`       | Human / System         | review result                             | 默认设置为 `Pending Review`                              | Yes      |
| `received_at`         | Raw Lead JSON / System | `received_at` or current time             | 使用 lead 原始创建时间；没有则用系统当前时间             | No       |
| `processed_at`        | System                 | current time                              | 使用系统处理完成时间                                     | No       |

## 3. Processing Log Field Mapping

| CRM Field         | Source Step  | Source Field       | Transformation Rule                     | Required |
| ----------------- | ------------ | ------------------ | --------------------------------------- | -------- |
| `log_id`          | System       | generated          | 生成唯一 log ID                         | Yes      |
| `lead_id`         | Python / CRM | `lead_id`          | 关联对应 lead 记录                      | Yes      |
| `workflow_run_id` | n8n          | execution ID       | 保存 n8n workflow 执行 ID               | Yes      |
| `step_name`       | n8n / System | current node name  | 必须匹配 Select Options                 | Yes      |
| `status`          | n8n / System | step result        | 设置为 `Success`、`Failed` 或 `Skipped` | Yes      |
| `error_message`   | n8n / System | error details      | 成功时为空；失败时记录错误详情          | No       |
| `raw_ai_output`   | AI Analysis  | raw model response | 保存原始 AI 输出，只用于 debug          | No       |
| `received_at`     | System       | current time       | 日志创建时间                            | Yes      |
