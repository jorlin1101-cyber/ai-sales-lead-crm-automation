# Day Review - 2026-05-28

## 1. 今日任务目标

今天的目标是完成 AI Sales Lead CRM MVP 的单条端到端测试。

测试对象为高价值 B2B lead：Mark Chen / Global Asia Travel。

核心目标不是批量处理，而是先验证一条 lead 能否稳定完成以下流程：

Webhook 接收 processed lead
→ Normalize 统一数据结构
→ IF 判断是否 valid
→ AI Lead Analysis
→ Parse and Validate AI Output
→ Merge 原始 lead 与 AI 输出
→ Notion Leads Table 写入
→ Processing Log 写入
→ High-value B2B 内部通知触发

## 2. 今日完成的 workflow 节点

### 2.1 Webhook - Receive Processed Lead

作用：接收 Python 预处理后的单条 lead。

测试结果：

- POST 请求成功
- 返回 200
- 收到 lead_id: `sample_b2b_mark_chen`

### 2.2 Code - Normalize Webhook Body

作用：统一 Webhook 输入结构。

原因：

Webhook 输出可能是 `$json.body.xxx`，也可能是 `$json.xxx`。
Normalize 节点把入口数据统一成平铺结构，方便后续 IF、AI、Notion 节点使用。

测试结果：

- 输出已平铺
- `lead_id = sample_b2b_mark_chen`
- `is_valid = true`

### 2.3 IF - Is Valid Lead

作用：判断 lead 是否进入 AI 分析。

规则：

- `is_valid = true` → 进入 AI 分析
- `is_valid = false` → 跳过 AI，写入 Processing Log

测试结果：

- Mark Chen 走 true branch
- invalid missing name lead 走 false branch

### 2.4 AI Lead Analysis

作用：对 valid lead 做语义分析。

Mark Chen 输出结果：

- `lead_type = B2B`
- `b2b_category = Overseas Travel Agency`
- `intent_level = High`
- `lead_score = 85`

### 2.5 Code - Parse and Validate AI Output

作用：解析并校验 AI 输出。

校验内容包括：

- 是否能解析为 JSON
- 是否包含全部 required fields
- enum 值是否合法
- `lead_score` 是否为 0-100 整数
- 是否存在 extra fields

测试结果：

- AI 输出为纯 JSON
- Parse and Validate 节点成功通过

### 2.6 Code - Merge Lead and AI Output

作用：把原始 lead 和 AI 分析结果合并成完整 CRM record。

合并后的数据用于写入 Notion Leads Table。

### 2.7 Notion - Create Lead Page

作用：将完整 lead 写入 Notion Leads Table。

测试结果：

- Mark Chen 页面创建成功
- `ai_analysis_status = Completed`
- `crm_status = Created`
- `review_status = Pending Review`

### 2.8 Notion - Create Success Log

作用：记录 workflow 成功执行日志。

测试结果：

- Processing Log 新增成功
- `step_name = Notion Create Lead`
- `status = Success`

### 2.9 IF - High-value B2B

作用：判断是否触发内部通知。

规则：

- `lead_type = B2B`
- `intent_level = High`
- `lead_score >= 80`

测试结果：

- Mark Chen 走 true branch

### 2.10 Set - Internal Notification Payload

作用：模拟内部通知 payload。

测试结果：

- 通知 payload 成功输出
- `notification_type = High-value B2B Lead`
- `lead_score = 85`

## 3. Invalid Branch 补测

测试对象：

- `lead_id = sample_invalid_missing_name`
- `is_valid = false`
- `error_reason = Name is required`

测试结果：

- IF 走 false branch
- AI Lead Analysis 没有执行
- Processing Log 新增 Skipped 日志

日志内容：

- `step_name = AI Lead Analysis`
- `status = Skipped`
- `error_message = Name is required`

## 4. 今日关键执行记录

| 测试场景 | Execution ID | 结果 |
|---|---:|---|
| Mark Chen valid high-value B2B | 340 | Success |
| Invalid missing name | 341 | Skipped log created |

## 5. 今日修正的问题

### 5.1 Webhook 输入结构不稳定

问题：

Webhook 输出可能是 `$json.body.xxx`，也可能是 `$json.xxx`。

解决：

新增 Normalize Code 节点，将入口数据统一成平铺结构。

### 5.2 AI 输出结构可能不稳定

问题：

AI 输出可能是字符串、对象、Markdown 包裹 JSON，或者额外字段。

解决：

新增 Parse and Validate Code 节点，对 AI 输出做结构校验。

### 5.3 `intent_level` 和 `lead_score` 可能不一致

问题：

第一次模型输出 `intent_level = High`，但 `lead_score = 75`，和评分规则冲突。

解决：

在 prompt 中补充一致性规则：

`High = 80-100`, `Medium = 50-79`, `Low = 0-49`

### 5.4 Leads Table 状态和 Processing Log 状态容易混淆

问题：

一开始把 Leads Table 的 `ai_analysis_status` 和 `crm_status` 写成了 `Success`。

修正：

Leads Table 使用业务阶段状态：

- `ai_analysis_status = Completed`
- `crm_status = Created`

Processing Log 使用执行结果状态：

- `Success`
- `Failed`
- `Skipped`

## 6. 今日技术收获

今天最重要的技术收获是：

n8n 工作流不是简单地把节点串起来，而是要明确每个节点的数据职责。

Webhook 负责接收数据，Normalize 负责统一入口结构，IF 负责流程分流，AI 负责语义判断，Parse 负责结构校验，Merge 负责装配完整 CRM record，Notion 负责存储，Processing Log 负责追踪执行结果。

只有每一层职责清楚，workflow 才能稳定调试和扩展。

## 7. 当前状态

当前已完成：

- Valid high-value B2B 单条端到端路径
- Invalid skipped 分支路径
- Notion Leads 写入
- Processing Log 写入
- 高分 B2B 内部通知模拟

当前还未完成：

- 12 条 leads 批量测试
- AI 输出异常处理分支
- Notion 写入失败处理
- 真实通知渠道接入
- README 和求职展示材料
