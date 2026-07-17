# Week 2 Interview Notes

## 项目名称

AI Sales Lead CRM Automation

## 当前阶段

Week 2：LLM 分析 + CRM 集成 + n8n 工作流闭环

## 项目一句话介绍

这个项目是一个面向小型入境游公司的 AI Sales Lead 自动化处理系统。它可以接收原始客户咨询，完成 lead 清洗、字段校验、LLM 分析、fallback 兜底、意向等级判断、follow-up email draft 生成，并通过 n8n 写入 Notion CRM 和 Processing Log。

---

# 1. 这个项目解决了什么业务问题？

小型入境游公司在处理外部咨询 lead 时，常见问题是效率低、优先级不清、跟进不稳定。

销售或运营人员通常需要手动查看每条咨询，判断客户类型、意向强弱、是否值得优先跟进，并手动整理摘要和回复邮件。这会导致高价值 lead 被忽略，低价值 lead 占用时间，跟进标准也不稳定。

本项目通过自动化流程，把原始咨询信息转换成结构化 CRM 记录。系统会自动完成清洗、校验、分析、评分、摘要生成、推荐动作生成和 follow-up email draft 生成。处理结果会通过 n8n 写入 Notion CRM，销售或运营人员可以快速查看高价值 lead，并基于系统生成的 draft 进行人工审核和跟进。

---

# 2. 当前系统完整流程

当前系统流程如下：

```text
Raw Lead
→ FastAPI /process-lead
→ Pydantic RawLeadInput
→ clean_lead()
→ validate_lead()
→ analyze_lead()
→ LLM-first analysis
→ rule_fallback if LLM fails
→ LeadProcessingResult
→ n8n routing
→ Notion Leads CRM
→ Processing Log
```

n8n 工作流流程如下：

```text
Generate Test Leads
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

# 3. FastAPI 在系统里的职责是什么？

FastAPI 是系统的核心业务 API 层。

它负责暴露 `/process-lead` endpoint，并调用后端 service 层完成 lead 的清洗、校验、LLM 分析、rule fallback 和结构化结果返回。

FastAPI 返回的核心对象是：

```text
LeadProcessingResult
```

其中包括：

```text
cleaned_lead
validation_result
analysis_result
```

FastAPI 的职责不是做外部系统编排。它不负责 Notion 写入，也不负责 workflow 分支连接。它负责保证输入 lead 被稳定处理，并返回结构化结果。

n8n 只消费 FastAPI 返回的结构化输出，然后负责分支路由、字段准备、写入 Notion 和创建 Processing Log。

---

# 4. n8n 在系统里的职责是什么？

n8n 负责外部工作流编排。

它主要负责：

```text
调用 FastAPI
根据 validation_result 做 valid / invalid 分支
根据 analysis_result.intent_level 做 High / Medium / Low 分流
通过 Prepare 节点标准化字段
合并所有分支
写入 Notion Leads CRM
创建 Processing Log
```

n8n 不直接实现清洗、校验、评分、LLM prompt、Pydantic 校验或 fallback 逻辑。

这些核心业务逻辑放在 Python/FastAPI 后端中，原因是 Python 更适合做稳定业务逻辑、单元测试、数据模型约束和版本管理。n8n 更适合做系统集成和流程编排。

---

# 5. 为什么不把所有逻辑都写在 n8n 里？

因为清洗、校验、评分和 LLM 分析属于稳定业务逻辑，不适合全部堆在 n8n 节点里。

如果把这些逻辑写在 n8n 中，会出现几个问题：

```text
逻辑分散
测试困难
版本管理困难
字段契约不稳定
复用性差
复杂分支难维护
```

放在 Python service 层有几个好处：

```text
可以用 Pydantic 定义数据契约
可以用 pytest 做自动化测试
可以拆分 cleaning / validation / scoring / ai_analysis / processor
可以让 n8n 只依赖稳定 API 输出
后续可以复用到其他入口，例如 Webhook、CRM、表单或前端
```

所以当前架构是：

```text
Python/FastAPI 处理核心业务逻辑
n8n 处理外部系统编排
Notion 存储 CRM 和日志记录
```

---

# 6. 为什么要用 Pydantic？

Pydantic 用来定义系统边界的数据契约。

当前项目中的关键模型包括：

```text
RawLeadInput
CleanedLead
LeadValidationResult
LeadAnalysisResult
LeadProcessingResult
```

Pydantic 的价值包括：

```text
校验输入字段类型
校验必填字段
限制 enum 值
限制 lead_score 范围
限制 confidence 范围
防止脏数据进入下游
防止错误 LLM 输出进入 CRM
```

例如 `LeadAnalysisResult` 中的字段有明确约束：

```text
lead_type: B2B / B2C / Unknown
intent_level: High / Medium / Low / Unknown
lead_score: 0–100
confidence: 0–1
analysis_method: llm / rule_fallback
```

这样 n8n 和 Notion 可以依赖稳定字段，不需要处理不可控的原始文本。

在这个项目里，Pydantic 不只是类型提示，而是系统的数据边界和稳定性保护层。

---

# 7. 为什么要做 LLM fallback？

因为 LLM 是不稳定的外部依赖。

它可能出现：

```text
网络错误
代理错误
API key 错误
余额不足
限流
模型不可用
返回空内容
返回非法 JSON
返回字段缺失
返回 enum 值错误
Pydantic schema 校验失败
```

如果没有 fallback，一旦 LLM 调用失败，整个 lead processing workflow 就会中断。n8n 后续节点无法稳定执行，Notion CRM 也可能没有记录。

所以系统采用：

```text
LLM-first + rule_fallback
```

策略如下：

```text
LLM 调用成功
→ 返回 analysis_method = llm

LLM 调用失败 / JSON 解析失败 / Pydantic 校验失败
→ 返回 analysis_method = rule_fallback
```

fallback 返回的仍然是同一套 `LeadAnalysisResult` schema。这样 n8n 和 Notion 不需要关心分析结果来自 LLM 还是规则兜底，它们只消费统一的 `analysis_result`。

这是一种系统韧性设计，不只是备用方案。

---

# 8. DeepSeek JSON mode 和 OpenAI Structured Outputs 的区别是什么？

DeepSeek JSON mode 主要保证模型输出是合法 JSON。

它不能保证输出一定符合业务 schema。

例如下面内容是合法 JSON：

```json
{
  "intent_level": "high",
  "confidence": "0.9"
}
```

但它不符合当前项目的 `LeadAnalysisResult` schema，因为：

```text
intent_level 必须是 High / Medium / Low / Unknown
confidence 必须是数字，而不是字符串
```

OpenAI Structured Outputs 更进一步，可以基于提供的 JSON Schema 约束模型输出，使输出更接近指定 schema。

所以当前项目里：

```text
DeepSeek JSON mode
→ 保证输出尽量是 JSON

OpenAI Structured Outputs
→ 更强地约束输出符合 schema

Pydantic
→ 做最终业务 schema 校验
```

DeepSeek 路径的处理链路是：

```text
response_format={"type": "json_object"}
→ json.loads()
→ LeadAnalysisResult.model_validate()
→ 如果校验失败，进入 rule_fallback
```

核心结论：

```text
JSON mode 保证 JSON 形态。
Structured Outputs 约束 schema。
Pydantic 负责最终业务校验。
```

---

# 9. 为什么 LLM 输出不能直接写入 CRM？

LLM 输出不能直接写入 CRM，因为它是不可信的外部生成内容。

它可能出现：

```text
缺字段
字段类型错误
enum 值错误
分数超范围
confidence 格式错误
返回额外无用字段
返回非法 JSON
编造原始 lead 中不存在的信息
```

所以必须经过以下链路：

```text
LLM raw response
→ JSON parse
→ Pydantic model_validate
→ LeadAnalysisResult
→ LeadProcessingResult.analysis_result
→ n8n
→ Notion CRM
```

只有通过 Pydantic 校验的结构化结果，才允许进入下游工作流。

这能避免 CRM 中出现脏字段、错字段和不可控内容。

---

# 10. 为什么返回 analysis_result，而不是 score_result？

早期版本只做规则评分，所以可以返回 `score_result`。

但当前系统已经不只是评分，还包括：

```text
lead_type
lead_subtype
intent_level
lead_score
lead_summary
recommended_action
followup_email_draft
analysis_method
confidence
```

这些字段共同构成完整的 lead 分析结果。

所以现在返回：

```text
analysis_result
```

它是统一的下游输出契约。

`analysis_result` 可以来自：

```text
LLM analysis
rule_fallback
```

但它们都符合同一套 `LeadAnalysisResult` schema。

这样 n8n、Notion 和后续系统不需要关心结果来源，只需要消费统一字段。

---

# 11. 为什么 invalid lead 要先拦截？

因为 invalid lead 的返回结果中：

```text
analysis_result = null
```

如果 n8n 不先判断：

```text
validation_result.is_valid
```

就直接访问：

```text
analysis_result.intent_level
```

流程就可能出错。

所以 n8n 必须先做 valid / invalid 判断：

```text
IF validation_result.is_valid == false
→ Invalid branch

IF validation_result.is_valid == true
→ Switch analysis_result.intent_level
```

这是一种防御式 workflow 设计。

---

# 12. High / Medium / Low / Invalid 分支分别代表什么？

## High

High 表示高价值或高意向 lead。

典型信号：

```text
旅行社或 operator 咨询
明确询价
大团
私人定制
有清楚时间或人数
有具体产品需求
```

业务动作：

```text
crm_status = To Review
priority = High
next_step = Review immediately and prepare personalized follow-up.
```

## Medium

Medium 表示有一定意向，但信息还不完整。

典型信号：

```text
询问 itinerary
有旅行兴趣
但缺少日期、预算、人数或目的地细节
```

业务动作：

```text
crm_status = To Review
priority = Medium
next_step = Review and collect missing travel details.
```

## Low

Low 表示有效但意向较弱。

典型信号：

```text
泛泛咨询
信息较少
没有明确预订或询价
```

业务动作：

```text
crm_status = Low Priority
priority = Low
next_step = Keep in CRM and follow up later if needed.
```

## Invalid

Invalid 表示 lead 未通过基础校验。

典型原因：

```text
邮箱格式错误
邮箱为空
message 为空
缺少必填字段
```

业务动作：

```text
crm_status = Invalid
priority = None
next_step = Fix missing or invalid lead data before further processing.
```

当前流程中，High / Medium / Low / Invalid 都会写入 Notion Leads CRM，并且都会写入 Processing Log。

---

# 13. 为什么要有 Prepare 节点？

Prepare 节点负责字段标准化。

FastAPI 返回的是嵌套结构：

```text
cleaned_lead.email
validation_result.is_valid
analysis_result.intent_level
analysis_result.lead_score
```

Notion 更适合接收扁平字段：

```text
email
is_valid
intent_level
lead_score
```

所以每个分支后面都需要 Prepare 节点，把嵌套结果转换成统一字段结构。

Prepare 节点还会添加 CRM 专用字段：

```text
crm_status
priority
next_step
```

所有 Prepare 节点必须输出同一套字段名。这样后面的 Merge 和 Notion Create Lead 节点才能稳定工作。

---

# 14. 为什么要 Merge 后只接一个 Notion Create Lead 节点？

因为四个分支最终都要写入同一个 Notion Leads CRM。

如果每个分支都接一个 Notion 节点：

```text
High → Notion
Medium → Notion
Low → Notion
Invalid → Notion
```

会产生重复配置。

问题包括：

```text
字段映射重复
新增字段要改四遍
维护成本高
容易出现某个分支字段漏改
后续排错困难
```

当前做法是：

```text
Prepare High / Medium / Low / Invalid
→ Merge All Leads
→ One Create Notion Lead node
```

好处是：

```text
减少重复配置
降低维护成本
保证字段映射一致
```

---

# 15. Processing Log 的价值是什么？

Processing Log 不是简单“记录日志”。

它让系统具备：

```text
可追踪性
可审计性
可排错性
可评估性
```

当前 Processing Log 记录：

```text
log_id
lead_id
step
status
message
analysis_method
created_at
```

它可以回答这些问题：

```text
某条 lead 是否成功写入 CRM？
这条 lead 是 LLM 分析还是 rule_fallback？
当前流程停在哪一步？
是 FastAPI 失败、LLM 失败、n8n 分支错误，还是 Notion 写入失败？
某一天 fallback 频率是否异常？
invalid lead 比例是否过高？
```

后续还可以用 Processing Log 统计：

```text
LLM 成功率
fallback 频率
无效 lead 比例
Notion 写入成功率
不同 intent_level 的分布
系统稳定性
```

所以 Processing Log 是让自动化系统从“能跑”变成“可观察、可诊断、可评估”的关键模块。

---

# 16. 当前已完成的功能

Week 2 当前已完成：

```text
FastAPI /process-lead
Pydantic schema
lead cleaning
lead validation
rule-based scoring
LLM prompt builder
DeepSeek LLM integration
OpenAI-compatible client support
DeepSeek JSON mode
Pydantic validation for LLM output
LLM-first + rule_fallback
n8n valid / invalid routing
n8n High / Medium / Low routing
Prepare standardized fields
Merge branches
Notion Leads CRM write
Notion Processing Log write
API contract documentation
LLM provider configuration documentation
n8n workflow documentation
Week 2 interview notes
```

---

# 17. 当前验证结果

当前测试结果：

```text
pytest: 104 passed, 1 warning
```

FastAPI 验证：

```text
/health: 正常
/process-lead: 正常
```

手动 LLM 测试结果：

```text
manual LLM test analysis_method: llm
LLM output fields complete: yes
obvious fabrication: no
```

n8n 全链路验证结果：

```text
n8n LLM full workflow test: passed
Create Notion Lead output: 4 items
Create Processing Log output: 4 items
valid leads analysis_method: llm
```

Notion 写入验证：

```text
Leads CRM: 4 records created
Processing Log: 4 records created
```

---

# 18. 当前项目架构亮点

这个项目目前可以在面试中强调以下亮点：

```text
业务问题明确
FastAPI 与 n8n 边界清晰
Pydantic 数据契约稳定
LLM 输出经过 schema 校验
DeepSeek 真实 API 调用已跑通
LLM-first + fallback 保证系统韧性
n8n 负责外部编排而非堆业务逻辑
Notion CRM 完成持久化
Processing Log 提供可追踪性
pytest 测试保护核心逻辑
文档覆盖 API contract、LLM provider config 和 n8n workflow
```

---

# 19. 面试时的 60 秒项目介绍

这个项目是一个面向小型入境游公司的 AI Sales Lead CRM Automation 系统，目标是解决人工处理客户咨询效率低、优先级不清和跟进不稳定的问题。

系统通过 FastAPI 暴露 `/process-lead` 接口，接收原始 lead 后，使用 Pydantic 做数据契约约束，再经过清洗、校验、LLM 分析和 rule fallback，最终返回统一的 `LeadProcessingResult`。

LLM 部分接入了 DeepSeek 的 OpenAI-compatible API，使用 JSON mode 获取结构化输出，再通过 Pydantic 的 `LeadAnalysisResult` 做最终 schema 校验。如果 LLM 调用失败或校验失败，系统会自动进入 rule_fallback，保证下游流程不中断。

n8n 负责外部工作流编排，根据校验结果和 intent_level 做分支路由，把标准化字段写入 Notion Leads CRM，并创建 Processing Log 用于追踪和排错。目前全链路已经验证通过，测试结果是 104 passed, 1 warning。

---

# 20. 面试时不能说错的点

## 不要说：n8n 负责所有业务逻辑

正确说法：

```text
n8n 负责外部工作流编排，核心业务逻辑在 FastAPI service 层。
```

## 不要说：DeepSeek Structured Outputs

正确说法：

```text
DeepSeek JSON mode + Pydantic validation。
```

## 不要说：LLM 输出直接写 CRM

正确说法：

```text
LLM 输出必须经过 JSON parse 和 Pydantic model_validate，验证为 LeadAnalysisResult 后才进入下游。
```

## 不要说：fallback 是备用功能

正确说法：

```text
fallback 是系统韧性设计，用来保证 LLM 失败时 workflow 仍然稳定运行。
```

## 不要说：Processing Log 只是记录一下

正确说法：

```text
Processing Log 提供可追踪性、可审计性、可排错性和后续评估基础。
```

---

# 21. 面试官可能追问

## Q1：如果 LLM 输出了合法 JSON，但字段不符合你的 schema，怎么办？

会通过 `LeadAnalysisResult.model_validate()` 做 Pydantic 校验。如果字段缺失、类型错误、enum 值不合法或数值越界，就抛出错误，并进入 rule_fallback。

---

## Q2：为什么 invalid lead 仍然要写入 CRM？

因为 invalid lead 也有业务价值。它可以帮助团队追踪数据质量问题，例如表单配置错误、垃圾 lead、邮箱格式问题或渠道质量问题。

如果直接丢弃 invalid lead，后续就无法评估 lead 来源质量。

---

## Q3：为什么要有 analysis_method 字段？

`analysis_method` 用来标记分析结果来源。

可能值是：

```text
llm
rule_fallback
```

它可以帮助销售人员理解结果可靠性，也可以帮助后续统计 LLM 成功率和 fallback 频率。

---

## Q4：如果 Notion 写入失败怎么办？

当前版本已经完成成功路径和 Processing Log，但 Notion 写入失败分支还没有做完整增强。

后续可以增加：

```text
Notion error branch
retry mechanism
failed log record
alert notification
dead-letter queue
```

当前项目处于 v1 阶段，优先完成核心闭环。

---

## Q5：这个项目后续怎么扩展？

后续可以扩展：

```text
RAG 知识库，用于生成更符合产品资料的 follow-up draft
Gmail draft 自动创建
High priority lead 自动通知
duplicate lead detection
run-level execution log
部署到云端
Webhook 接入真实表单
评估模块，用于追踪 LLM 输出质量
```

---

# 22. Week 2 总结

Week 2 的核心目标是把项目从“规则评分 demo”推进到“真实 LLM + CRM 自动化闭环”。

当前已经完成：

```text
真实 DeepSeek LLM 调用
结构化输出校验
fallback 容错
FastAPI API contract
n8n workflow 编排
Notion CRM 写入
Processing Log 记录
pytest 自动化测试
核心文档沉淀
```

当前版本已经具备面试展示价值，但还不是最终产品。

下一阶段应该进入 Week 3：

```text
RAG 知识库最小版
```

目标是让 follow-up email draft 和 recommended_action 不只依赖通用 LLM 判断，而是能够引用公司产品资料、目的地资料和销售规则，生成更符合业务上下文的回复建议。
