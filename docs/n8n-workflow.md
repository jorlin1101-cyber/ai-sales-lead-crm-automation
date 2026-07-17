# n8n 工作流说明

## 概述

本文档说明 AI Sales Lead CRM Automation 项目中的 n8n 工作流设计。

n8n 负责外部工作流编排。它接收或生成 lead 输入，调用 FastAPI 后端，根据校验结果和意向等级进行分流，标准化字段，写入 Notion CRM，并创建处理日志。

核心业务逻辑不放在 n8n 里，而是放在 FastAPI service 层。

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
→ valid / invalid 分流
→ High / Medium / Low 分流
→ 字段准备
→ 合并分支
→ 写入 Notion Leads CRM
→ 写入 Processing Log
```

n8n 不应该重复实现 Python 里的业务逻辑。它应该消费 FastAPI 返回的结构化结果，并协调外部系统。

---

## 当前工作流

当前工作流如下：

```text
Manual Trigger / Generate Test Leads
→ HTTP Request to FastAPI /process-lead
→ IF validation_result.is_valid
→ Switch analysis_result.intent_level
→ Prepare High / Medium / Low / Invalid Lead
→ Merge All Leads
→ Create Notion Lead
→ Prepare Processing Log
→ Create Processing Log
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
```

对于 valid lead，`analysis_result` 包含 lead 分析结果。

对于 invalid lead，`analysis_result` 为 `null`。

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
analysis_result.intent_level
```

原因是 invalid lead 的结果是：

```text
analysis_result = null
```

在校验分流之前直接访问 `analysis_result.intent_level` 是不安全的。

---

## 4. Switch 节点：意向等级分流

Switch 节点检查：

```text
analysis_result.intent_level
```

当前工作流支持三个 valid intent 分支：

```text
High
Medium
Low
```

意向等级由后端分析层生成，来源可能是：

```text
llm
rule_fallback
```

具体来源由下面字段标记：

```text
analysis_result.analysis_method
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
消息为空
缺少必填字段
```

分支输出：

```text
crm_status = Invalid
priority = None
next_step = Fix missing or invalid lead data before further processing.
```

Invalid leads 仍然会写入 Leads CRM，这样可以追踪数据质量问题。

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
analysis_result.intent_level
analysis_result.lead_score
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
lead_id
name
email
company_name
message
source
is_valid
error_reason
lead_type
lead_subtype
intent_level
lead_score
lead_summary
recommended_action
followup_email_draft
analysis_method
confidence
crm_status
priority
next_step
```

Invalid leads 应该使用默认分析值：

```text
lead_type = Unknown
lead_subtype = Unknown
intent_level = Unknown
lead_score = 0
analysis_method = none 或空值
confidence = 0
```

---

## 7. Merge 节点

四个 Prepare 分支之后，工作流会合并所有标准化 lead items。

Merge 结构如下：

```text
Prepare High Lead + Prepare Medium Lead
→ Merge High Medium

Merge High Medium + Prepare Low Lead
→ Merge Valid Leads

Merge Valid Leads + Prepare Invalid Lead
→ Merge All Leads
```

Merge 模式为：

```text
Append
```

预期输出：

```text
Merge High Medium: 2 items
Merge Valid Leads: 3 items
Merge All Leads: 4 items
```

---

## 为什么要在 Notion 前合并

工作流在合并所有分支后，只使用一个最终的 Notion Create Lead 节点。

这样可以避免四个重复的 Notion 节点：

```text
High → Notion
Medium → Notion
Low → Notion
Invalid → Notion
```

使用单一 Notion 节点有三个好处：

```text
减少重复配置
降低维护成本
保证字段映射一致
```

如果以后新增一个 CRM 字段，只需要映射一次。

---

## 8. Create Notion Lead

Create Notion Lead 节点把标准化 lead 记录写入：

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
error_reason
intent_level
lead_score
analysis_method
crm_status
priority
next_step
```

---

## 9. Prepare Processing Log

当一条 lead 成功写入 Notion Leads CRM 后，工作流会准备一条 processing log 记录。

Log 是在 CRM 写入之后创建的，而不是之前。

原因：

```text
success log 只能在 Notion Lead 记录真实创建成功之后再生成。
```

Log 字段包括：

```text
log_id
lead_id
step
status
message
analysis_method
created_at
```

示例：

```text
step = notion_lead_created
status = success
message = Lead successfully written to Notion CRM.
```

---

## 10. Create Processing Log

Create Processing Log 节点把记录写入：

```text
AI Sales Processing Log
```

测试执行的预期结果：

```text
创建 4 条 processing log 记录
```

每条 processing log 记录都应该关联被处理的 `lead_id`。

---

## 当前验证结果

当前已验证的工作流结果：

```text
HTTP Request: 4 items
Merge All Leads: 4 items
Create Notion Lead: 4 items
Prepare Processing Log: 4 items
Create Processing Log: 4 items
```

完整 LLM 工作流也已验证：

```text
valid leads analysis_method = llm
invalid lead 单独处理
Notion Leads CRM 写入通过
Processing Log 写入通过
```

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
