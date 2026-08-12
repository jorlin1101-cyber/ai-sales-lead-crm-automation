# n8n 工作流说明

## 概述

本文档说明 AI Sales Lead CRM Automation 项目中的 n8n 工作流设计。

n8n 负责外部工作流编排。它接收或生成 lead 输入，调用 FastAPI 后端，根据校验结果和意向等级进行分流，标准化字段，写入 Notion CRM，并创建处理日志。

核心业务逻辑不放在 n8n 里，而是放在 FastAPI service 层。

项目提供可安全导入的公开工作流骨架：

```text
n8n/ai-sales-lead-routing.json
```

该 JSON 不包含 credential、Notion database ID、生产 URL 或真实客户数据。导入后需要在
`CRM Connector Placeholder` 和 `Processing Log Connector Placeholder` 位置配置自己的
Notion 或其他 CRM 连接器。

---

## 系统边界

### FastAPI 的职责

FastAPI 负责核心 lead 处理逻辑：

```text
RawLeadInput
→ clean_lead()
→ validate_lead()
→ analyze_lead()
→ LeadProcessingResult
```

后端负责：

```text
数据清洗
字段校验
LLM-first lead 分析
规则 fallback
Pydantic 响应校验
稳定的 API 响应契约
```

### n8n 的职责

n8n 负责工作流编排：

```text
lead 输入
→ 向 FastAPI 发送 HTTP 请求
→ API Success / API Error 分流
→ valid / invalid 分流
→ High / Medium / Low 分流
→ 字段准备
→ 统一 CRM payload
→ CRM Connector Placeholder
→ 安全 Processing Log payload
```

n8n 不应该重复实现 Python 里的业务逻辑。它应该消费 FastAPI 返回的结构化结果，并协调外部系统。

---

## 当前工作流

当前工作流如下：

```text
Manual Trigger / Generate Test Leads
→ Normalize API Input
→ HTTP Request to FastAPI /process-lead
→ Classify API Result
→ Transport Success / API Error
→ IF validation_result.is_valid
→ Switch analysis_result.decision.intent_level
→ Prepare High / Medium / Low / Invalid / API Error
→ Unified CRM Payload
→ CRM Connector Placeholder
→ Prepare Safe Processing Log
→ Processing Log Connector Placeholder
```

---

## 节点设计说明

## 1. Manual Trigger / Generate Test Leads

这个节点用于本地测试。

它生成 4 条测试 lead：

```text
1 条 invalid lead
1 条 High lead
1 条 Medium lead
1 条 Low lead
```

目的：在一次执行中验证所有工作流分支。

---

## 2. HTTP Request to FastAPI

HTTP Request 节点调用：

```text
POST http://127.0.0.1:8000/process-lead
```

请求体包含一条原始 lead item。

FastAPI 返回：

```text
cleaned_lead
validation_result
analysis_result
sources
```

对于 valid lead，`analysis_result` 包含 lead 分析结果。响应头包含：

```text
X-Request-ID
```

n8n 应保存这个 ID，用于 API Error 分支和日志关联。

对于 invalid lead，`analysis_result` 为 `null`。

当前版本已接入 RAG；成功检索时 `sources` 返回 1～3 个脱敏来源。来源只包含
`chunk_id`、`source_title`、`section` 和 `rank`。

### HTTP Request 之前的输入 adapter

FastAPI 只接受标准字段 `company_name`。如果旧表单仍输出 `company`，必须在 HTTP Request 之前使用 Set 或 Code 节点显式转换：

```text
company → company_name
删除 company
```

如果不转换，`RawLeadInput` 的 `extra="forbid"` 会让请求返回 HTTP 422。不得依赖 FastAPI 静默丢弃旧字段，也不得从 message 中猜测 `company_name`。

---

## 3. IF 节点：校验分流

IF 节点检查：

```text
validation_result.is_valid
```

如果为 false，lead 进入 Invalid 分支。

如果为 true，lead 进入 intent-level Switch 节点。

这个校验必须在访问下面字段之前完成：

```text
analysis_result.decision.intent_level
```

原因是 invalid lead 的结果是：

```text
analysis_result = null
```

在校验分流之前直接访问 `analysis_result.decision.intent_level` 是不安全的。

HTTP 422、500 和 503 不属于 Invalid。它们是 Transport Error，必须先进入 API Error
分支。API Error 读取稳定字段：

```text
detail.code
detail.message
detail.request_id
```

---

## 4. Switch 节点：意向等级分流

Switch 节点检查：

```text
analysis_result.decision.intent_level
```

当前工作流支持三个 valid intent 分支：

```text
High
Medium
Low
```

意向等级由后端分析层生成，来源可能是：

```text
llm_features
rule_features
```

具体来源由下面字段标记：

```text
analysis_result.metadata.analysis_method
```

---

## 5. Lead 分支

## High Priority 分支

High priority leads 是具有强销售意向或高订单价值的有效 lead。

典型信号包括：

```text
询价请求
大团
私人定制旅行
旅行社或操作商询问
清晰的旅行计划细节
```

分支输出：

```text
crm_status = To Review
priority = High
next_step = Review immediately and prepare personalized follow-up.
```

---

## Medium Priority 分支

Medium priority leads 是具有一定意向，但购买信号还不完整的有效 lead。

典型信号包括：

```text
询问信息
对私人旅行感兴趣
有一定计划意向
缺少日期、预算或人数细节
```

分支输出：

```text
crm_status = To Review
priority = Medium
next_step = Review and collect missing travel details.
```

---

## Low Priority 分支

Low priority leads 是意向较弱或信息较少的有效 lead。

典型信号包括：

```text
泛泛的旅行兴趣
消息内容有限
没有明确询价或预订请求
信息完整度较低
```

分支输出：

```text
crm_status = Low Priority
priority = Low
next_step = Keep in CRM and follow up later if needed.
```

---

## Invalid 分支

Invalid leads 是未通过校验的 lead。

示例：

```text
邮箱格式错误
邮箱为空
清洗后消息只剩空白
```

缺少 `email`、缺少 `message` 或 `message=""` 属于请求结构错误，会返回 HTTP 422，应进入 API Error 分支，而不是 Invalid 分支。

分支输出：

```text
crm_status = Invalid
priority = None
next_step = Fix missing or invalid lead data before further processing.
```

Invalid leads 仍然会写入 Leads CRM，这样可以追踪数据质量问题。

## API Error 分支

API Error 表示请求结构错误或后端服务故障，例如：

```text
request_validation_error
authentication_error
configuration_error
rag_unavailable
internal_error
```

该分支不得把 Transport Error 伪装成 Domain Invalid。它输出：

```text
crm_status = Processing Error
request_id = API 返回的 request ID
error_codes = [detail.code]
next_step = Inspect API logs using the request ID.
```

---

## 6. Prepare 节点

每个分支都有一个 Prepare 节点：

```text
Prepare High Lead
Prepare Medium Lead
Prepare Low Lead
Prepare Invalid Lead
```

Prepare 节点负责字段标准化。

它们会把嵌套的 API 响应字段，例如：

```text
cleaned_lead.email
validation_result.is_valid
analysis_result.decision.intent_level
analysis_result.decision.lead_score
```

转换成扁平结构：

```text
email
is_valid
intent_level
lead_score
```

它们还会添加 CRM 专用字段：

```text
crm_status
priority
next_step
```

所有 Prepare 节点必须输出同一套字段名。

这样可以保证后续 Notion 字段映射稳定。

---

## 标准化输出字段

每个 Prepare 节点应该输出：

```text
request_id
lead_id
external_lead_id
name
email
company_name
message
source
is_valid
error_codes
lead_type
lead_subtype
intent_level
lead_score
lead_summary
recommended_action
followup_email_draft
analysis_method
fallback_reason
disposition
needs_review
policy_version
sources
crm_status
priority
next_step
```

对于 valid lead，Prepare 节点可以展开 `analysis_result`。对于 invalid lead，必须保留：

```text
analysis_result = null
sources = []
```

不得为 invalid lead 伪造 `lead_type=Unknown`、`lead_score=0` 等分析结果。如果 CRM 使用扁平字段，这些分析字段应该写入 null 或留空。

---

## 7. 统一 CRM Payload

High、Medium、Low、Invalid 和 API Error 五个分支最终进入同一个统一 CRM payload 节点。

公开工作流把五个 Prepare 节点都连接到 `Unified CRM Payload`。这个 No Operation 节点只统一
下游入口，不修改数据：

```text
Prepare High Lead ──────┐
Prepare Medium Lead ────┤
Prepare Low Lead ───────┤
Prepare Invalid Lead ───┼→ Unified CRM Payload
Prepare API Error ──────┘
```

---

## 为什么要在 Notion 前合并

工作流在统一所有分支后，只保留一个 CRM 连接器位置。

这样可以避免五个重复的 CRM 节点：

```text
High → Notion
Medium → Notion
Low → Notion
Invalid → Notion
API Error → Notion
```

使用单一 Notion 节点有三个好处：

```text
减少重复配置
降低维护成本
保证字段映射一致
```

如果以后新增一个 CRM 字段，只需要映射一次。

---

## 8. CRM Connector Placeholder

公开工作流不内置 Notion credential 或 database ID。导入后可将占位节点替换成 Notion
Create Database Page 或其他 CRM 节点。映射时消费统一 payload，不得重新计算评分。

私有配置可以把标准化 lead 记录写入：

```text
AI Sales Leads CRM
```

测试执行的预期结果：

```text
创建 4 条 lead 记录
1 条 Invalid
1 条 High
1 条 Medium
1 条 Low
```

重点检查字段：

```text
lead_id
email
is_valid
error_codes
intent_level
lead_score
analysis_method
sources
crm_status
priority
next_step
```

---

## 9. Prepare Processing Log

公开工作流当前准备的是 `routing_completed` 日志，它只表示路由和 payload 准备完成，不冒充
CRM 写入成功：

```text
routing_completed != notion_lead_created
```

Log 字段包括：

```text
request_id
lead_id
route
step
status
policy_version
```

用户接入真实 CRM 后，只有在 CRM 节点真实成功之后，才能追加
`notion_lead_created / success` 日志。

---

## 10. Processing Log Connector Placeholder

公开工作流只准备脱敏 processing log。导入后可将占位节点替换为 Notion、数据库或日志
服务。Processing Log 不包含完整 email 和 message。

```text
AI Sales Processing Log
```

每条非 Transport Error 日志关联 `lead_id`；API Error 使用 `request_id` 进行追踪。

---

## 当前公开资产的验证范围

自动化测试会验证：

```text
JSON 可解析
节点 ID 和名称唯一
High / Medium / Low / Invalid / API Error 五个分支存在
HTTP Request 调用 /process-lead
不包含 credentials、database ID、真实邮箱或本机路径
n8n 不复制 PolicyV1 评分规则
```

公开 JSON 的目标是安全导入和展示路由结构。真实 Notion 写入需要使用者在自己的 n8n
环境中配置凭据后单独验收，不能把私有环境运行结果冒充为公开离线测试结果。

公开工作流默认按“n8n 与 FastAPI 都直接运行在同一台电脑上”的方式调用 FastAPI：

```text
http://127.0.0.1:8000/process-lead
```

如果 n8n 运行在 Docker 中、FastAPI 直接运行在 Windows 主机上，请把 URL 改为：

```text
http://host.docker.internal:8000/process-lead
```

如果 FastAPI 部署在其他主机，也请在 n8n 的 `Call FastAPI Process Lead` 节点中修改 URL。
工作流不读取 `$env`，避免在启用了环境变量访问保护的 n8n 实例中导入后报错。

---

## 架构决策

该工作流遵循以下设计原则：

```text
Python 处理核心业务逻辑。
n8n 处理外部流程编排。
Notion 存储 CRM 和处理记录。
```

这样可以保持系统可维护。

如果 lead 分析规则变化，应该更新 Python service 层。

如果工作流路由或外部系统集成变化，应该更新 n8n。

如果 CRM 字段变化，应该更新 Prepare 节点和 Notion 映射。

---

## n8n 不应该做什么

n8n 不应该包含下面这些逻辑的重复版本：

```text
邮箱校验规则
lead 评分逻辑
LLM prompt 逻辑
Pydantic schema 校验
fallback 分析逻辑
```

这些应该属于 Python 后端。

n8n 只应该消费稳定的 API 输出，并协调下游工具。

---

## 后续改进方向

可能的后续改进：

```text
添加 High priority 通知
添加 Gmail draft 创建
添加 Notion 写入失败重试
添加 HTTP Request 失败分支
添加重复 lead 检测
添加 run-level execution log
通过 webhook 或表单接入生产触发器
```

这些应该在当前 CRM 和 Processing Log 流程稳定之后再添加。
