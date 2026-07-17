# AI Sales Lead Cleaner API

AI Sales Lead Cleaner API 是一个用于 AI Sales 自动化流程的 Lead 清洗、校验、评分 API 服务。

系统接收外部 lead JSON，完成字段标准化、业务校验、规则评分，并返回结构化处理结果。该服务可以被 n8n、CRM、前端页面或其他业务系统通过 HTTP API 调用。

---

## 1. Problem

在销售自动化流程中，来自表单、n8n、CSV 或外部 API 的 lead 数据通常存在以下问题：

- 字段格式不统一
- email 大小写和空格混乱
- source 缺失
- 无效 lead 可能进入 CRM
- lead 意向和价值难以快速判断
- 在 n8n 中直接写复杂业务逻辑不方便测试和维护

本项目将核心 lead 处理逻辑放在 Python / FastAPI 服务中，使清洗、校验、评分流程更加稳定、可测试、可复用。

---

## 2. Features

当前已完成功能：

- 使用 Pydantic 定义输入和输出数据契约
- 清洗 lead 字段：
  - 去除前后空格
  - email 小写化
  - source 默认值处理
  - 生成 lead_id
- 校验 lead 是否有效：
  - empty_email
  - invalid_email_format
  - empty_message
  - valid
- 对有效 lead 进行规则评分
- 对无效 lead 跳过评分
- 支持 B2B 与高价值 B2C lead 分类
- 返回统一的 LeadProcessingResult
- 提供 FastAPI 接口
- 支持 Swagger UI 调试
- 使用 pytest 覆盖 schema、service、processor 和 API 测试

---

## 3. Tech Stack

- Python 3.14
- FastAPI
- Pydantic
- pytest
- Uvicorn
- httpx / FastAPI TestClient

---

## 4. Project Structure

```text
ai-sales-lead-crm-automation/
├── src/
│   └── lead_cleaner/
│       ├── api/
│       │   ├── __init__.py
│       │   └── main.py
│       ├── schemas/
│       │   ├── __init__.py
│       │   └── lead.py
│       └── services/
│           ├── __init__.py
│           ├── cleaning.py
│           ├── validation.py
│           ├── scoring.py
│           └── processor.py
├── tests/
│   ├── test_api.py
│   ├── test_cleaning.py
│   ├── test_processor.py
│   ├── test_schema_lead.py
│   ├── test_scoring.py
│   └── test_validation.py
├── docs/
│   ├── lead-analysis-strategy.md
│   └── scoring-rules.md
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## 5. Core Data Flow

```text
RawLeadInput
→ clean_lead()
→ CleanedLead
→ validate_lead()
→ LeadValidationResult
→ score_lead()
→ LeadScoreResult
→ process_lead()
→ LeadProcessingResult
```

说明：

- `RawLeadInput`：外部输入数据契约
- `CleanedLead`：清洗后的 lead 数据
- `LeadValidationResult`：业务校验结果
- `LeadScoreResult`：规则评分结果
- `LeadProcessingResult`：完整处理流程返回结果

无效 lead 不会进入评分流程：

```text
invalid email
→ validation_result.is_valid = false
→ score_result = null
```

---

## 6. Setup

### 6.1 Create virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 6.2 Install dependencies

```powershell
python -m pip install -r requirements.txt
```

---

## 7. Run Tests

Run all tests:

```powershell
python -m pytest
```

当前测试覆盖：

- Pydantic schema validation
- Lead cleaning logic
- Lead validation logic
- Rule-based scoring logic
- End-to-end lead processing
- FastAPI API behavior

当前测试状态：

```text
======================== warnings summary =========================
.venv\Lib\site-packages\fastapi\testclient.py:1
  D:\Python project\ai-sales-lead-crm-automation\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================== 67 passed, 1 warning in 0.46s ==================
```

---

## 8. Run API Server

Start FastAPI server:

```powershell
$env:PYTHONPATH="src"
uvicorn lead_cleaner.api.main:app --reload
```

Open API docs:

```text
http://127.0.0.1:8000/docs
```

---

## 9. API Usage

### 9.1 Health Check

```http
GET /health
```

Response:

```json
{
  "status": "ok"
}
```

---

### 9.2 Process Lead

```http
POST /process-lead
```

Request body:

```json
{
  "name": "John Doe",
  "email": "john@example.com",
  "company_name": "Spain Travel Agency",
  "message": "We want a quotation for a 20 people private tour to China in September.",
  "source": "Website"
}
```

Response example:

```json
{
  "cleaned_lead": {
    "lead_id": "...",
    "name": "John Doe",
    "email": "john@example.com",
    "company_name": "Spain Travel Agency",
    "message": "We want a quotation for a 20 people private tour to China in September.",
    "source": "Website"
  },
  "validation_result": {
    "is_valid": true,
    "error_reason": "valid"
  },
  "score_result": {
    "lead_type": "B2B",
    "lead_subtype": "Agency",
    "intent_level": "High",
    "lead_score": 100
  }
}
```

注意：`lead_score` 以实际规则计算结果为准。如果本地返回不是 100，请按实际结果修改 README 示例。

---

## 10. Validation Behavior

### Case 1: Business validation failed

如果请求体结构合法，但 email 格式业务上无效：

```json
{
  "name": "Bad Lead",
  "email": "invalid-email",
  "company_name": "Example Corp",
  "message": "I am interested in your product.",
  "source": "Website"
}
```

API 返回 HTTP 200，但业务校验失败：

```json
{
  "validation_result": {
    "is_valid": false,
    "error_reason": "invalid_email_format"
  },
  "score_result": null
}
```

### Case 2: Request body validation failed

如果请求体缺少必填字段 `email`：

```json
{
  "name": "No Email",
  "company_name": "Example Corp",
  "message": "I am interested in your product.",
  "source": "Website"
}
```

FastAPI 会在进入业务逻辑前返回：

```text
422 Unprocessable Entity
```

区别：

```text
422 = 请求体不符合 RawLeadInput 数据契约
200 + is_valid=false = 请求体结构合法，但业务校验失败
```

---

## 11. Rule-based Scoring

当前评分是 rule-based fallback，不是最终 AI 判断。

评分维度包括：

```text
customer_type_score
+ intent_score
+ order_value_score
+ information_completeness_score
= lead_score
```

当前可识别：

```text
B2B:
- Agency
- Operator
- School
- Corporate
- Influencer

B2C:
- LargeGroup
- PrivateCustom
- LuxuryHighBudget
- FIT

Unknown:
- Unknown
```

`intent_level` 根据最终分数映射：

```text
75–100 → High
45–74  → Medium
0–44   → Low
```

详细规则见：

```text
docs/scoring-rules.md
```

---

## 12. Lead Analysis Strategy

系统未来采用：

```text
LLM-first + rule-based fallback
```

当前阶段先完成规则评分 fallback。

未来阶段：

- LLM 可用时，优先使用 LLM 做复杂语义判断
- LLM 不可用、超时、输出不合法时，回退到规则评分
- LLM 输出必须经过 Pydantic 校验
- 不允许模型结果未经校验直接写入 CRM

详细策略见：

```text
docs/lead-analysis-strategy.md
```

---

## 13. Current Limitations

当前版本限制：

- 评分逻辑仍然依赖关键词规则
- 暂未接入 LLM
- 暂未接入数据库
- 暂未接入 n8n
- 暂未接入 Notion / CRM 写入
- 暂未加入 API 鉴权
- 暂未加入 Docker 部署
- 对复杂语义、否定表达和非英文文本支持有限

---

## 14. Roadmap

下一步计划：

- 编写 README 和运行说明
- 使用 n8n HTTP Request 调用 FastAPI
- 接入 LLM structured output
- 加入 LLM fallback 机制
- 保存处理日志和调用结果
- 接入 Notion / CRM
- 加入 PostgreSQL 数据持久化
- 加入 Docker Compose 部署
- 编写项目面试问答文档

---

## 15. Interview Summary

这个项目的核心设计是：

- 用 Pydantic 固定数据契约
- 用 service 层承载核心业务逻辑
- 用 processor.py 串联单条 lead 的完整处理流程
- 用 FastAPI 暴露 HTTP API
- 用 pytest 保证 schema、service、processor 和 API 行为稳定
- 当前规则评分作为 LLM 不可用时的 fallback
- 后续将接入 LLM structured output 和 n8n 自动化流程

面试中可以这样概括：

```text
我把 lead 清洗、校验和评分逻辑从 n8n 中抽离出来，放到 Python / FastAPI 服务中实现。
这样核心逻辑可以用 pytest 测试，也可以通过 HTTP API 被 n8n、CRM 或前端复用。
当前评分模块是 rule-based fallback，后续会接入 LLM structured output，并在 LLM 失败时自动回退到规则评分。
```
