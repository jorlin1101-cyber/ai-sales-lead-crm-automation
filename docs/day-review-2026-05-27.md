# Day Review - 2026-05-27

## 1. 今日任务目标

今天的核心目标是完成 AI Lead Analysis 设计层。

这一层的作用是：在 Python 预处理层完成字段清洗和基础校验之后，让 AI 对有效 lead 进行语义判断，并输出稳定、可校验、可被 n8n 和 Notion CRM 使用的结构化结果。

今天没有进入 n8n 节点搭建，因为 AI 输出结构如果不稳定，后续 n8n 解析、Notion 写入和高分 lead 通知都会出现问题。

## 2. 今日完成内容

今天完成了以下文件：

- `docs/ai-output-schema.md`
- `docs/lead-scoring-rules.md`
- `prompts/lead-analysis-prompt.md`
- `exports/ai-analysis-samples.json`

## 3. AI 输出字段设计

AI Lead Analysis 最终输出以下字段：

- `lead_type`
- `b2b_category`
- `intent_level`
- `lead_score`
- `lead_summary`
- `recommended_action`
- `follow_up_email`

这些字段对应后续 Notion CRM 中的 AI 分析字段，也会被 n8n 用于条件判断、字段映射和高分 B2B lead 通知。

## 4. 为什么需要 JSON Schema

AI 输出不能依赖自由文本。

如果 AI 输出自由文本，后续 n8n 很难稳定解析，也容易出现字段缺失、字段命名不一致、类型错误或额外字段。

JSON Schema 的作用是约束 AI 输出结构，包括：

- 必须输出哪些字段
- 字段类型是什么
- 枚举值只能有哪些
- `lead_score` 必须是 0-100 的整数
- 不允许输出额外字段

这能让 AI 分析结果更稳定，也能降低 n8n 和 Notion 映射失败的风险。

## 5. Lead Score 评分规则

今天设计了 100 分制的 `lead_score` 规则。

评分维度包括：

- Business Potential
- Demand Clarity
- Timeline / Urgency
- Decision Power / Budget Signal
- Service Fit / Message Quality

评分规则的目标不是让 AI “凭感觉打分”，而是让每个 lead 的优先级判断更可解释、可复盘。

## 6. `intent_level` 和 `lead_score` 的区别

`intent_level` 是优先级标签，分为 `High`、`Medium`、`Low`。

`lead_score` 是量化分数，范围是 0-100。

两者的关系是：

- 80-100：通常对应 `High`
- 50-79：通常对应 `Medium`
- 0-49：通常对应 `Low`

`intent_level` 方便人工快速理解，`lead_score` 方便系统排序、筛选和触发自动化条件。

## 7. Invalid Lead 处理规则

`is_valid = false` 的 lead 不进入 AI Lead Analysis。

原因是 invalid lead 属于基础字段问题，例如缺少 name、email 或 message。这类问题应该由 Python 预处理层确定性判断，不需要消耗 AI 分析成本。

invalid lead 应该：

- `ai_analysis_status = Skipped`
- `review_status = Rejected`
- 写入 Processing Log 用于审计和排错

## 8. Spam Lead 处理规则

Spam 或 low-value lead 不应该在 Python 阶段直接拦截。

原因是 spam 属于语义判断，需要理解 message 的内容、意图和上下文。

Python 只负责判断字段是否完整。
AI 负责判断内容是否低价值、无关、广告推广或疑似垃圾信息。

对于 `Spam / Low-value` lead：

- `intent_level = Low`
- `lead_score` 通常为 0-20
- `b2b_category = None`
- `follow_up_email = ""`
- `recommended_action` 应建议不跟进

## 9. 高分 B2B Lead 通知规则

后续 n8n 工作流中，当 lead 满足以下条件时，应触发内部通知：

- `lead_type = B2B`
- `intent_level = High`
- `lead_score >= 80`

通知只能发送给内部人工审核人或销售人员，不能自动发给客户。

`follow_up_email` 只能作为人工审核用的草稿，不允许自动发送。

## 10. 今日发现的关键风险

### 风险 1：内容创作者容易被高估

AI 可能因为对方自称 blogger、influencer 或 creator 就自动给高分。

但内容创作者是否有价值，需要看平台链接、粉丝画像、受众匹配度、合作方式和具体商业价值。

### 风险 2：B2C 大团可能被低估

B2C lead 不一定低价值。

如果是多人私家团、近期出行、需求明确，也可能有较高成交价值，不能因为不是 B2B 就自动低分。

### 风险 3：简单咨询可能被误判为 spam

短消息不等于 spam。

例如 “How much is a Chengdu city tour?” 虽然信息少，但仍可能是真实咨询。应低分处理或继续索要信息，而不是直接判定为垃圾信息。

## 11. 今日技术收获

今天最重要的技术收获是：

AI 自动化工作流不能只依赖 prompt。必须先定义输出字段、JSON Schema、评分规则和样例标准，才能让 AI 结果稳定进入 n8n 和 Notion CRM。

Python 层负责确定性处理，AI 层负责语义判断，n8n 层负责流程编排，Notion 层负责结构化存储。每一层职责必须清楚，否则整个工作流会变得不可控。
