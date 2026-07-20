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
│           ├── rule_feature_extractor.py
│           ├── security_signal_detector.py
│           ├── policy_v1.py
│           ├── lead_analyzer.py
│           └── processor.py
├── tests/
│   ├── test_api.py
│   ├── test_cleaning.py
│   ├── test_processor.py
│   ├── test_schema_lead.py
│   ├── test_policy_v1.py
│   ├── test_rule_feature_extractor.py
│   ├── test_security_signal_detector.py
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
→ LeadFeatures + SecuritySignals
→ PolicyV1
→ LeadDecision
→ process_lead()
→ LeadProcessingResult
```

说明：

- `RawLeadInput`：外部输入数据契约
- `CleanedLead`：清洗后的 lead 数据
- `LeadValidationResult`：业务校验结果
- `LeadFeatures`：模型或规则提取的业务事实，以及服务端补充的确定性字段
- `SecuritySignals`：确定性安全复核信号
- `LeadDecision`：PolicyV1 产生的分类、分数、breakdown 和 disposition
- `LeadProcessingResult`：完整处理流程返回结果

无效 lead 不会进入评分流程：

```text
invalid email
→ validation_result.is_valid = false
→ analysis_result = null
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

## 11. Deterministic PolicyV1

最终评分只由服务端 `PolicyV1` 产生，不由 LLM 直接填写。评分维度包括：

```text
customer_fit（最高 30）
+ intent_strength（最高 30）
+ order_value_proxy（最高 25）
+ information_completeness（最高 15）
= lead_score
```

`score_breakdown` 会保存每个维度的得分和原因码，并由 Pydantic 保证分项之和等于最终分数。Spam override、manual review、qualified 和 nurture 的优先级也由同一个 PolicyV1 决定。

当前可识别的 lead 类型包括：

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

旧版独立评分入口已经删除，项目只保留 `LeadFeatures → PolicyV1 → LeadDecision` 这一条评分路径。

---

## 12. Lead Analysis Strategy

系统当前采用：

```text
LLM / rule feature extraction
→ SecuritySignals
→ PolicyV1
→ LeadDecision
```

- LLM 只提取受限业务特征，不返回分数、intent 或 disposition。
- LLM 不可用或输出不合法时，回退到规则特征提取。
- 两条提取路径共用同一个 PolicyV1。
- 模型输出必须经过严格 Pydantic 校验。
- 客户文本和模型都不能填写服务端 provenance。
- 中英文可疑注入进入人工复核，不能把分数改成客户指定的值。

---

## 13. Current Limitations

当前版本限制：

- PolicyV1 权重和阈值仍是工程业务假设，尚未用真实转化数据校准
- 规则特征提取对复杂语义的能力有限
- live provider 的运行模式和配置工厂尚待 Day 4 收口
- 暂未接入数据库
- 暂未加入 API 鉴权
- 暂未加入 Docker 部署
- RAG 尚未接入 `/process-lead` 主流程

---

## 14. Roadmap

下一步计划：

- 完成 `demo / live / rule_only` 三种显式运行模式
- 完成 provider factory、timeout 和分类 fallback reason
- 将 RAG 和 recommendation 接入主流程，但不允许修改 LeadDecision
- 更新 n8n 适配器读取嵌套分析契约
- 加入 PostgreSQL 数据持久化
- 加入 Docker Compose 部署
- 使用匿名真实转化数据校准 PolicyV1

---

## 15. Interview Summary

这个项目的核心设计是：

- 用 Pydantic 固定数据契约
- 用 service 层承载核心业务逻辑
- 用 processor.py 串联单条 lead 的完整处理流程
- 用 FastAPI 暴露 HTTP API
- 用 pytest 保证 schema、service、processor 和 API 行为稳定
- LLM 只负责提取受限业务事实
- PolicyV1 独立产生可解释、可回归的最终决策
- 模型失败时改用规则特征，但评分策略不变
- 安全信号和 provenance 均由服务端生成

面试中可以这样概括：

```text
我把 lead 清洗、校验、特征提取和决策逻辑从 n8n 中抽离到 Python / FastAPI 服务。
LLM 只能提取受限业务事实，最终分数、intent 和 disposition 全部由版本化的 PolicyV1 计算。
模型失败时系统改用规则特征提取，但仍经过同一个 PolicyV1，因此响应结构和决策规则保持稳定。
```
