# ADR 0001：Lead Contract V2

- 状态：已接受
- 日期：2026-07-17
- 决策负责人：项目维护者

## 背景

项目已经有一套可以运行的销售线索输入和响应契约，但其中一些规则还不够严格，不同文件之间也没有完全统一，暂时无法满足面试版 MVP 的要求。

目前存在以下问题：

- 请求中未定义的字段可能会被静默忽略。
- 缺少 `external_lead_id`，无法将一条线索追溯到外部表单或工作流。
- 大部分输入字符串没有最大长度限制。
- 邮箱验证目前只检查是否包含 `@` 和 `.`，可靠性不足。
- 验证结果只能返回一个 `error_reason`，无法同时报告多个业务数据问题。
- 当前响应契约还没有保证 invalid lead 一定返回 `sources=[]`。
- API、样例数据、CRM 文档和未来的 n8n 字段映射可能使用不一致的字段名。

项目需要一套唯一的公开契约，让 FastAPI、Python 服务、测试、样例数据、CLI、n8n 和 CRM 字段映射共同遵守。

## 决策

项目将引入唯一的 Lead Contract V2。

这套契约将明确区分“请求结构错误”和“业务数据无效”。

## 请求结构错误与业务数据无效

请求结构错误表示请求不符合 API 规定的结构，因此不能进入正常业务处理流程。

业务数据无效表示请求结构正确，但客户提交的销售线索不适合继续进行分析。

| 输入情况 | HTTP 状态码 | 处理结果 |
|---|---:|---|
| 缺少 `email` | 422 | 请求结构错误 |
| `email=""` | 200 | 业务数据无效：`empty_email` |
| email 格式错误 | 200 | 业务数据无效：`invalid_email_format` |
| 缺少 `message` | 422 | 请求结构错误 |
| `message=""` | 422 | 请求结构错误 |
| `message="   "` | 200 | 业务数据无效：`empty_message_after_cleaning` |
| 包含 `company` 等未定义字段 | 422 | 请求结构错误，并返回 `extra_forbidden` |
| message 超过 5000 个字符 | 422 | 请求结构错误 |

错误格式或空邮箱仍然被视为业务数据无效，而不是请求结构错误。原因是这条销售线索可能仍然需要被记录到 CRM 的处理日志中。

## RawLeadInput

`RawLeadInput` 将设置 `extra="forbid"`，禁止系统静默丢弃未定义的字段。

公开请求允许使用以下字段：

| 字段 | 是否必填 | 长度限制 |
|---|---:|---:|
| `external_lead_id` | 否 | 最长 100 个字符 |
| `name` | 否 | 最长 200 个字符 |
| `email` | 是 | 最长 320 个字符 |
| `company_name` | 否 | 最长 300 个字符 |
| `message` | 是 | 1～5000 个字符 |
| `source` | 否 | 最长 100 个字符 |

email 在请求模型中仍然使用普通字符串类型。

邮箱格式将在业务验证阶段进行检查，而不是由请求模型自动拒绝。

旧字段 `company` 不属于 API 契约。n8n adapter 可以在调用 API 之前，明确地把 `company` 转换为 `company_name`。

## CleanedLead

数据清洗服务将执行以下操作：

- 生成由服务端控制的 `lead_id`。
- 保留 `external_lead_id`，但不把它当作服务端生成的 ID。
- 删除字符串开头和结尾的空格。
- 将 email 转换为小写。
- 将缺失的 `name` 和 `company_name` 转换为空字符串。
- 将缺失或只有空格的 source 转换为 `Unknown`。
- 保留清洗后的 message，供后续处理使用。

项目现阶段不会因为增加了 `external_lead_id` 就声称已经实现真正的幂等处理。数据库唯一约束不属于当前 MVP 的范围。

## LeadValidationResult

验证结果将包含以下字段：

- `is_valid`：表示这条销售线索是否通过业务验证的布尔值
- `error_codes`：验证错误代码列表

允许使用的错误代码包括：

- `empty_email`
- `invalid_email_format`
- `empty_message_after_cleaning`

验证结果必须始终满足以下规则：

- 有效结果必须是 `is_valid=True`。
- 有效结果必须是 `error_codes=[]`。
- 无效结果必须是 `is_valid=False`。
- 无效结果必须至少包含一个错误代码。

当一条销售线索同时存在多个问题时，验证器可以返回多个错误代码。

契约不再增加 `validation_status`。原因是它与 `is_valid` 表达相同信息，同时保留会产生两个事实来源，并可能出现相互矛盾的状态。n8n 或 CRM 如果需要文字状态，可以根据 `is_valid` 显式映射为 `valid` 或 `invalid`。

## 处理响应

公开的处理结果将使用一套稳定、统一的响应结构。

对于 invalid lead：

- `analysis_result` 必须是 `None`。
- `sources` 必须是空列表。
- 不得调用特征提取器或分析器。
- 不得调用 RAG。
- 不得调用推荐内容生成服务。

业务数据无效时返回 HTTP 200，可以让 n8n 或 CRM 集成继续记录这次业务事件，而不是将其当作 API 本身发生故障。

## 字段命名

对外公开的标准字段名是 `company_name`。

API 内部不得静默地将以下字段视为 `company_name`：

- `company`
- `organization`
- `companyName`

外部 adapter 必须在发送请求之前，明确地将旧字段转换为标准字段。

## 影响

正面影响：

- 未定义字段不会再被静默丢弃。
- n8n 和 CRM 可以依赖更稳定、更可预测的 API 行为。
- invalid lead 不会浪费 LLM 或 RAG 资源。
- 可以通过 `external_lead_id` 追踪外部销售线索。
- 测试可以明确区分请求结构错误和业务数据无效。
- 后续的 PolicyV1 和 RAG 可以建立在稳定的响应结构上。

需要付出的成本和当前限制：

- 现有测试、样例数据和下游字段映射需要同步更新。
- 仍然发送 `company` 的客户端必须改为 `company_name`，或者使用明确的 adapter 进行转换。
- 项目必须保证 `is_valid` 和 `error_codes` 始终保持一致。
- 当前决策没有实现数据库级别的幂等性。

## 考虑过的其他方案

### 在 RawLeadInput 中直接使用 `EmailStr`

没有采用。

因为错误格式的 email 会在进入业务处理之前直接变成 HTTP 422。当前项目需要把邮箱格式错误的销售线索记录为业务数据无效事件。

### 继续忽略未定义字段

没有采用。

因为静默丢失字段很难被发现，并且可能造成 CRM 数据缺失。

### 继续只使用一个 `error_reason`

没有采用。

因为一条销售线索可能同时存在多个验证问题。

### 同时保留 V1 和 V2 两套模型

没有采用。

因为同时维护两套公开契约会增加混乱和维护成本。项目将迁移到唯一的一套契约。

## 不在本次决策范围内的内容

本 ADR 不负责实现以下内容：

- PolicyV1 评分
- Prompt Injection 检测
- live、demo 和 rule-only 三种运行模式
- RAG 检索
- 数据库幂等性
- n8n workflow 导出
- 自动发送邮件

这些功能将在项目后续阶段处理。
