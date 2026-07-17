# Lead Analysis Strategy

## 1. Purpose

本文档定义 AI Sales Automation System 的 lead 分析策略。

系统采用 **LLM-first + rule-based fallback** 的方式：

- 当 LLM 可用时，优先使用 LLM 进行意向判断、摘要生成和推荐动作生成。
- 当 LLM 不可用、超时、输出不合法或成本限制触发时，系统自动回退到规则评分。
- 规则评分作为稳定、低成本、可测试的 fallback，保证系统不会因为 LLM 失败而中断。

---

## 2. Overall Flow

整体流程如下：

```text
CleanedLead
→ validate_lead()
→ 如果 lead 有效：
    → 尝试 LLM analysis
    → 如果 LLM 成功并通过 Pydantic 校验：
        → 使用 LLM analysis result
    → 如果 LLM 失败：
        → 使用 rule-based scoring fallback
→ 返回统一分析结果
```

---

## 3. LLM Analysis Responsibility

LLM 主要负责复杂语义判断和文本生成。

LLM 负责：

- 判断 `lead_type`
- 判断 `b2b_subtype`
- 判断 `intent_level`
- 生成 `lead_score`
- 生成 `lead_summary`
- 生成 `recommended_action`
- 生成 `followup_email_draft`

LLM 输出必须经过 Pydantic 校验，不能直接写入 CRM。

---

## 4. Rule-based Fallback Responsibility

规则评分负责提供稳定的基础判断。

规则评分负责：

- 基础 `lead_type`
- 基础 `b2b_subtype`
- 基础 `intent_level`
- 基础 `lead_score`

规则评分的特点：

- 稳定
- 低成本
- 可测试
- 可解释
- 不依赖外部 API
- 可作为 LLM 失败时的 fallback

---

## 5. Fallback Conditions

以下情况触发 fallback：

- LLM API 不可用
- API key 缺失
- 请求超时
- LLM 返回内容不是合法 JSON
- LLM 输出无法通过 Pydantic 校验
- 成本控制策略要求关闭 LLM
- 模型服务返回错误

触发 fallback 后，系统使用 `scoring.py` 中的规则评分结果。

---

## 6. n8n Responsibility

n8n 不负责核心 AI 判断逻辑。

n8n 主要负责：

- Webhook 业务触发
- 调用 FastAPI 接口
- 写入 Notion / CRM
- 发送 Gmail / 飞书 / 企业微信通知
- 人工确认 human-in-the-loop
- 外部系统集成

核心 AI analysis 应该放在 Python / FastAPI 服务中，因为 Python 逻辑更容易测试、维护和做结构化校验。

---

## 7. Python Service Responsibility

Python / FastAPI 服务负责：

- Pydantic 数据契约
- lead 清洗
- lead 校验
- 规则评分 fallback
- LLM structured output
- LLM 输出校验
- retry / timeout / fallback
- 日志记录
- 返回统一 API response

---

## 8. Design Reason

这个设计避免系统完全依赖 LLM。

如果只使用 LLM，系统会面临：

- 输出不稳定
- 成本不可控
- API 失败导致流程中断
- 测试困难
- 结果难以解释

如果只使用规则评分，系统会面临：

- 语义理解能力弱
- 难以处理复杂表达
- 无法生成摘要、推荐动作和邮件草稿

因此，最终采用：

```text
LLM-first + rule-based fallback
```

LLM 负责复杂语义能力，规则评分负责稳定兜底。

---

## 9. Current Phase

当前阶段先实现 `scoring.py` 作为规则评分 fallback。

当前不直接接入 LLM。

原因：

- 还没有完成 LLM client
- 还没有完成 prompt template
- 还没有完成 Structured Output schema
- 还没有完成 retry / timeout / fallback 机制
- 还没有完成 mock test

所以当前顺序是：

```text
1. 完成 rule-based scoring fallback
2. 完成 FastAPI API 封装
3. 让 n8n 调用 FastAPI
4. 下一阶段再接入 LLM analysis
```

---

## 10. Future LLM Integration

后续会新增：

- `services/ai_analysis.py`
- `services/llm_client.py`
- `services/prompt_builder.py`
- `services/lead_analyzer.py`
- `schemas/ai_output.py`

未来流程会变成：

```text
CleanedLead
→ validate_lead()
→ 如果 valid：
    → 优先尝试 LLM analysis
    → 如果 LLM 成功并通过 Pydantic 校验：
        → 使用 LLM result
    → 如果 LLM 失败：
        → fallback 到 scoring.py
```

---

## 11. Interview Explanation

面试时可以这样解释：

我采用 LLM-first + rule-based fallback 的设计。
当 LLM 可用时，系统会优先使用 LLM 做复杂语义判断、客户摘要、推荐动作和邮件草稿生成。
但我不会完全依赖 LLM，因为 LLM 可能超时、输出不合法、成本过高或 API 不可用。

所以我保留了一套规则评分 baseline。
规则评分稳定、便宜、可测试，可以在 LLM 失败时作为 fallback。
LLM 输出也会经过 Pydantic 校验，校验失败不会直接写入 CRM，而是降级到规则评分并记录失败原因。

---

## 12. Implementation Order

当前实现顺序：

```text
1. docs/lead-analysis-strategy.md
2. services/scoring.py
3. tests/test_scoring.py
4. api/main.py
5. n8n 调用 FastAPI
6. 第 2 周再实现 LLM analysis
```
