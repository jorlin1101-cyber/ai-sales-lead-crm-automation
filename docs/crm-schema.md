# CRM Schema


## 1. Design Principles

本 CRM schema 用于 AI Sales Lead Research & CRM Automation v1 MVP。字段设计遵循以下原则：

1. 每个字段必须服务一个明确动作，例如字段校验、AI 分析、CRM 写入、人工审核、通知或日志追踪。
2. 原始输入字段、AI 生成字段、系统状态字段、人工审核字段必须分开，不混用。
3. 能使用固定选项的字段优先使用 Select，避免自由文本造成数据混乱。
4. 长文本内容使用 Long Text，例如 `message`、`lead_summary`、`follow_up_email`。
5. 时间字段必须使用 Date / DateTime，不允许用 Text 或 Select。
6. v1 只保留能跑通 MVP 闭环的字段，不追求完整企业级 CRM。
7. Leads Table 记录一条销售线索的当前状态；Processing Log Table 记录系统每一步处理过程。
8. 一条 lead 可以对应多条 processing logs，因此日志必须单独建表，不能塞进 Lead 表。

## 2. Leads Table

| Field Name            | Field Type         | Required | Created By        | Purpose                                 | v1  |
| --------------------- | ------------------ | -------: | ----------------- | --------------------------------------- | --- |
| `lead_id`             | Text / ID          |      Yes | System            | 唯一识别一条 lead，方便日志和自动化追踪 | Yes |
| `name`                | Text               |      Yes | Customer          | 识别联系人                              | Yes |
| `email`               | Email              |      Yes | Customer          | 联系客户、生成 follow-up email          | Yes |
| `company_name`        | Text               |       No | Customer / AI     | 识别潜在 B2B 公司或机构                 | Yes |
| `message`             | Long Text          |      Yes | Customer          | 保存原始咨询内容，供 AI 分析            | Yes |
| `source`              | Select             |      Yes | Customer / System | 记录线索来源                            | Yes |
| `is_valid`            | Checkbox / Boolean |      Yes | System            | 判断 lead 是否通过基础字段校验          | Yes |
| `error_reason`        | Long Text          |       No | System            | 记录无效原因，例如缺少 email            | Yes |
| `lead_type`           | Select             |       No | AI                | 判断 lead 是 B2B / B2C / Unknown        | Yes |
| `b2b_category`        | Select             |       No | AI                | 判断 B2B 子类型                         | Yes |
| `intent_level`        | Select             |       No | AI                | 判断跟进优先级                          | Yes |
| `lead_score`          | Number             |       No | AI                | 量化销售优先级，范围 0-100，必须为整数            | Yes |
| `lead_summary`        | Long Text          |       No | AI                | 用一句话总结 lead 内容                  | Yes |
| `recommended_action`  | Long Text          |       No | AI                | 给出下一步跟进建议                      | Yes |
| `follow_up_email`     | Long Text          |       No | AI                | 生成邮件草稿，不自动发送                | Yes |
| `ai_analysis_status`  | Select             |      Yes | System            | 记录 AI 分析业务阶段                    | Yes |
| `crm_status`          | Select             |      Yes | System / n8n      | 记录 CRM 页面创建状态                       | Yes |
| `notification_status` | Select             |       Yes | System / n8n      | 记录是否已通知人工审核                  | Yes |
| `review_status`       | Select             |      Yes | Human / System    | 记录人工审核状态                        | Yes |
| `received_at`         | DateTime           |       No | System            | 记录 lead 收到时间                      | Yes |
| `processed_at`        | DateTime           |       No | System            | 记录 lead 被处理时间                    | Yes |

## 3. Processing Log Table

| Field Name        | Field Type      | Required | Created By   | Purpose                      | v1  |
| ----------------- | --------------- | -------: | ------------ | ---------------------------- | --- |
| `log_id`          | Text / ID       |      Yes | System       | 唯一识别一条处理日志         | Yes |
| `lead_id` | Text | Yes | System | 关联对应 lead | Yes |
| `workflow_run_id` | Text            |      Yes | n8n / System | 追踪一次 workflow 执行       | Yes |
| `step_name`       | Select          |      Yes | System       | 记录当前执行步骤             | Yes |
| `status` | Select | Yes | System | 记录该步骤成功、失败或跳过 | Yes |
| `error_message`   | Long Text       |       No | System       | 保存错误详情                 | Yes |
| `raw_ai_output`   | Long Text       |       No | AI           | 保存原始 AI 输出，方便 debug | Yes |
| `created_at`     | DateTime        |      Yes | System       | 记录日志创建时间             | Yes |

## 4. Select Options

| Field Name            | Options                                                                                                                                                    |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `source`              | `Reddit`, `Website`, `Email`, `LinkedIn`, `Instagram`, `WeChat`, `Manual`, `Unknown`                                                                                 |
| `lead_type`           | `B2B`, `B2C`, `Unknown`, `Spam / Low-value`                                                                                                                |
| `b2b_category`        | `Overseas Travel Agency`, `DMC / Ground Operator`, `Corporate Client`, `Content Creator / Media`, `Local Partner`, `Other B2B`, `None`                   |
| `intent_level`        | `High`, `Medium`, `Low`, `Unknown`                                                                                                                         |
| `ai_analysis_status`  | `Not Started`, `Completed`, `Failed`, `Skipped`                                                                                                           |
| `crm_status`          | `Not Started`, `Created`, `Failed`                                                                                                                        |
| `notification_status` | `Not Required`, `Pending`, `Sent`, `Failed`                                                                                                                |
| `review_status`       | `Pending Review`, `Approved`, `Rejected`, `Needs More Info`                                                                                                |
| `step_name`           | `Read Input`, `Clean Fields`, `Validate Lead`, `AI Analysis`, `AI Lead Analysis`, `CRM Mapping`, `CRM Write`, `Notion Create Lead`, `Notification`, `Logging`                 |
| `status`              | `Success`, `Failed`, `Skipped`                                                                                                                             |

### Status Semantics

`Leads` Table 的状态字段描述的是一条 lead 当前所处的业务阶段，例如 `ai_analysis_status = Completed`、`crm_status = Created`。

`Processing Log` Table 的 `status` 字段描述的是某一个 workflow step 的执行结果，只允许使用 `Success`、`Failed`、`Skipped`。

## 5. Field Naming Rules

1. 所有字段名统一使用英文 `snake_case`。
2. 不使用中文字段名作为系统字段。
3. 不使用空格、斜杠、括号或特殊符号。
4. 字段名必须语义单一，不能把多个意思塞进一个字段。
5. AI 输出字段必须和 prompt JSON schema 保持一致。
6. CRM 字段名必须和 n8n 字段映射保持一致。
7. 状态字段统一使用 `_status` 结尾，例如 `crm_status`、`review_status`。
8. 时间字段统一使用 `_at` 结尾，例如 `received_at`、`processed_at`、`created_at`。

## 5.1 Default Status Rules

### Valid lead

当 `is_valid = true` 时，系统默认状态为：

| Field | Default Value |
|---|---|
| `ai_analysis_status` | `Not Started` |
| `crm_status` | `Not Started` |
| `notification_status` | `Not Required` |
| `review_status` | `Pending Review` |

### Invalid lead

当 `is_valid = false` 时，系统默认状态为：

| Field | Default Value |
|---|---|
| `ai_analysis_status` | `Skipped` |
| `crm_status` | `Not Started` |
| `notification_status` | `Not Required` |
| `review_status` | `Rejected` |

## 6. Deferred Fields

以下字段或数据对象暂不进入 v1，后续根据真实业务需求再考虑：

| Field / Object        | Reason                                                       |
| --------------------- | ------------------------------------------------------------ |
| `Organizations Table` | v1 阶段公司信息较少，先用 `company_name` 存在 Leads Table 中 |
| `Contacts Table`      | v1 不需要维护复杂联系人关系                                  |
| `Opportunities Table` | v1 不做完整销售 pipeline                                     |
| `deal_value`          | 当前无法稳定估算成交金额                                     |
| `budget`              | 客户不一定提供，v1 不作为必填                                |
| `travel_date`         | 对部分 B2C lead 有用，但不是 B2B 自动化闭环必需字段          |
| `group_size`          | 可后续加入报价和行程生成模块                                 |
| `final_lead_type`     | v1 先保留 AI 判断和人工审核状态，不单独维护最终分类          |
| `sent_email`          | v1 不自动发送邮件                                            |
| `payment_status`      | v1 不涉及收款                                                |





