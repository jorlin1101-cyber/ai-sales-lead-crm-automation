# 当前处理流程

下面的流程反映 Lead Contract V2 在 Day 2 结束时的真实边界。

```mermaid
flowchart TD
    A[External lead input] --> B[n8n adapter]
    B -->|company 显式改名为 company_name| C[POST /process-lead]
    C --> D{请求结构符合 RawLeadInput?}

    D -- No --> E[HTTP 422 transport error]
    E --> F[记录 API 错误日志]

    D -- Yes --> G[Python 清洗字段]
    G --> H[业务数据验证]
    H --> I{validation_result.is_valid?}

    I -- No --> J[保存 error_codes]
    J --> K[analysis_result = null]
    K --> L[sources = 空列表]
    L --> M[记录 invalid lead]

    I -- Yes --> N[当前分析服务]
    N --> O[生成 analysis_result]
    O --> P[返回 sources；Day 2 为空列表]
    P --> Q[n8n 按 intent_level 分流]
    Q --> R[映射到 CRM 字段]
    R --> S[写入 Notion / Airtable CRM]
    S --> T[按规则决定是否通知人工审核]
    T --> U[保存 Processing Log]
```

## 契约要点

- API 只接受 `company_name`；旧字段 `company` 必须由 n8n adapter 显式转换。
- 缺少 `email` 或 `message` 属于 transport error，返回 HTTP 422。
- 空邮箱、错误邮箱或清洗后空白 message 属于 domain invalid，返回 HTTP 200。
- domain invalid 使用 `is_valid=false` 和 `error_codes`，不使用 `error_reason`。
- invalid lead 不进入分析或 RAG，也不伪造默认分析值。
- `external_lead_id` 用于追踪外部来源，但当前没有数据库唯一约束，不能声称已经幂等。
- 当前分析字段仍是过渡契约；Day 3 将实现 `LeadFeatures → PolicyV1 → LeadDecision`。
