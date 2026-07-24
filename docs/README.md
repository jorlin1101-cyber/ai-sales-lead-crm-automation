# Documentation

这里是当前有效文档的入口。README 只负责项目概览，详细契约和设计放在本目录。

## Current

| Document | Purpose |
| --- | --- |
| [API contract](api-contract.md) | 当前请求、响应、业务无效和传输错误契约 |
| [API example](api-example.md) | 完整请求与响应示例 |
| [Lead Contract ADR](adr/0001-lead-contract-v2.md) | 数据契约关键决策 |
| [Field mapping](field-mapping.md) | API、n8n 与 CRM 字段映射 |
| [CRM schema](crm-schema.md) | Leads 与 Processing Log 结构 |
| [RAG design](rag-design.md) | 混合检索设计背景 |
| [RAG evaluation](rag-evaluation.md) | 当前冻结评测和证据边界 |
| [n8n workflow](n8n-workflow.md) | 五路路由和连接器边界 |
| [Day 6 acceptance](day6-acceptance.md) | 核心场景验收矩阵 |

## Source of Truth

文档帮助理解代码，但最终行为必须由以下内容共同确认：

1. `src/lead_cleaner/schemas/`
2. `src/lead_cleaner/services/policy_v1.py`
3. `src/lead_cleaner/config.py`
4. `tests/`

如果文档和代码不一致，应先修正文档和测试，再提交改动。

## Archive

开发日志和已废弃设计已移至 [archive](archive/README.md)。归档内容只用于理解演进过程，
不能作为当前实现依据。
