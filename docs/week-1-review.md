很好。到这里，第 1 周主线闭环已经完成。

你现在已经跑通了完整链路：

```text
n8n
→ HTTP Request
→ FastAPI /process-lead
→ Pydantic request validation
→ clean_lead()
→ validate_lead()
→ score_lead()
→ process_lead()
→ LeadProcessingResult
→ n8n 分支判断
```

这已经不是“我会 n8n”了，而是：

```text
我能用 Python/FastAPI 构建可测试的业务 API，并让 n8n 调用它完成自动化编排。
```

这句话有面试价值。

---

## 现在立刻补到 `docs/run-summary.md`

在原来的 `n8n Integration Test` 后面追加：

````markdown
## 6. n8n Branching Test

n8n branching logic has been tested successfully.

Workflow:

```text
Manual Trigger
→ HTTP Request: POST /process-lead
→ IF: validation_result.is_valid
    false → Invalid Lead
    true  → Switch: score_result.intent_level
        High   → High Priority
        Medium → Normal Review
        Low    → Low Priority
````

Test cases:

```text
Valid high-value B2B agency lead
→ High Priority

Invalid email lead
→ Invalid Lead

Low-value FIT lead
→ Low Priority
```

Result:

```text
All branches worked as expected.
```

````

---

## 第 1 周完成情况

你已经完成：

```text
1. Pydantic 数据契约
2. cleaning service
3. validation service
4. scoring service
5. processor service
6. FastAPI API
7. pytest 自动化测试
8. README.md
9. requirements.txt
10. scoring-rules.md
11. lead-analysis-strategy.md
12. run-summary.md
13. n8n 调用 FastAPI
14. n8n 根据返回结果做分支
````

这是第 1 阶段的完整闭环。

---

## 下一步不要继续加功能

今天如果再继续接 Notion、Gmail、LLM，会开始乱。现在应该做**第 1 周复盘文档**，把成果固定下来。

创建：

```text
docs/week-1-review.md
```

写这几个部分：

````markdown
# Week 1 Review

## 1. Completed Deliverables

- Built Pydantic schemas for lead input, cleaned lead, validation result, scoring result, and processing result.
- Built service layer for cleaning, validation, scoring, and processing.
- Built FastAPI endpoints: GET /health and POST /process-lead.
- Added pytest coverage for schemas, services, processor, and API.
- Created README, requirements.txt, scoring rules, and lead analysis strategy docs.
- Connected n8n HTTP Request to FastAPI.
- Added n8n branching logic based on validation result and intent level.

## 2. Final Working Flow

```text
n8n
→ FastAPI
→ Pydantic
→ cleaning
→ validation
→ scoring
→ structured response
→ n8n branching
````

## 3. Key Engineering Concepts Learned

* Data contract with Pydantic
* Type hints and response models
* Service-layer separation
* FastAPI request body validation
* FastAPI response_model
* pytest testing strategy
* Rule-based fallback scoring
* n8n as orchestration layer, not core logic layer

## 4. Current Limitations

* No LLM analysis yet
* No database persistence yet
* No Notion / CRM write-back yet
* No authentication yet
* No Docker deployment yet
* Rule-based scoring still depends on keywords

## 5. Next Week Focus

Next week focus:

```text
LLM API + Structured Outputs + fallback design
```

Planned modules:

* schemas/ai_output.py
* services/llm_client.py
* services/prompt_builder.py
* services/ai_analysis.py
* services/lead_analyzer.py

Main goal:

```text
LLM available → use LLM analysis
LLM unavailable / invalid output → fallback to rule-based scoring
```

```

---

## 你现在最后回答我 4 个问题

别跳过。你要证明自己不是只会照做。

1. 为什么核心清洗、校验、评分逻辑不应该直接写在 n8n 里？
2. 为什么 FastAPI 路由层不应该写太多业务逻辑？
3. 为什么无效 lead 不应该进入 `score_lead()`？
4. 为什么规则评分即使不够智能，也要保留？

答完这 4 个问题，第 1 周我才算你真正过关。
```
