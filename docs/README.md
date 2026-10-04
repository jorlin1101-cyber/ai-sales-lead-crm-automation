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
| [Grounded recommendation](grounded-recommendation.md) | 可选 LLM 建议、引用校验和安全回落边界 |
| [Notion CRM](notion-crm.md) | 人工确认、幂等查询与 Notion 写入配置 |
| [Production readiness](production-readiness.md) | 面向真实业务的上线边界与待办清单 |
| [Multi-turn channel reply plan](multi-turn-channel-reply-plan.md) | 多渠道格式化回复与多轮上下文实施方案 |
| [n8n workflow](n8n-workflow.md) | 七路路由、人工审核和连接器边界 |
| [Workflow implementation review](workflow-implementation-review.md) | 2026-09-05 优化交付、逐项复核和未验证边界 |
| [Acceptance matrix](acceptance-matrix.md) | 核心场景与自动化证据矩阵 |

## Planning

| Document | Purpose |
| --- | --- |
| [分版本实施方案](implementation-roadmap-2026-10-04.md) | 基于 GitHub 04be2e5 的同步建议、P0/P1/P2 任务、P3 启动条件、依赖、指标与验收；实施进展见开发基线报告 |
| [开发基线验收报告](development-baseline-2026-10-04.md) | S0 已完成：原目录备份、新副本同步、实际测试结果、问题修复、启动与回退方法 |
| [P0-01 最终方案设计报告](p0-01-final-design.md) | 当前实施依据：已合并二审，包含 22 场景、双基线、模式评分、CI、工作包和 26 项验收 |
| [P0-01 开发与逐项验收](p0-01-implementation-acceptance.md) | 本次开发记录、26 项验收证据和未完成条件 |
| [P0-01 运行与接纳说明](p0-01-quality-operations.md) | 离线运行、报告、人工复核、正式基线与 CI 操作 |
| [P0-01 业务案例复核包](p0-01-business-review-pack.md) | 22 场景的业务要求、实测结果及已确认记录 |
| [P0-01 二次审核](p0-01-second-review-2026-10-04.md) | 代码回放和资料研究形成的 8 项修订；已纳入最终方案 |
| [P0-01 原详细设计](p0-01-baseline-and-failure-cases-design.md) | 历史设计，保留作审查依据；后续开发以最终方案为准 |

## Source of Truth

文档帮助理解代码，但最终行为必须由以下内容共同确认：

1. `src/lead_cleaner/schemas/`
2. `src/lead_cleaner/services/policy_v1.py`
3. `src/lead_cleaner/config.py`
4. `tests/`

如果文档和代码不一致，应先修正文档和测试，再提交改动。
