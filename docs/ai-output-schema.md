# AI 输出结构设计

> **历史文档（已被替代）：** 本文记录旧版“AI 直接输出评分”的设计。当前正式契约以 `schemas/policy.py`、`schemas/ai_output.py` 和 `docs/api-contract.md` 顶部的 Day 3 结构为准。

> **历史文档（已被替代）：** 本文记录旧版“AI 直接输出评分”的设计。当前正式契约以 `schemas/policy.py`、`schemas/ai_output.py` 和 `docs/api-contract.md` 顶部的 Day 3 结构为准。

> [!IMPORTANT]
> 本文件记录 Contract V2 之前的历史 AI 输出设计，不是当前 API 契约。
> 当前可执行契约以 `docs/api-contract.md` 和 Pydantic OpenAPI schema 为准；其中使用
> `lead_subtype`、`followup_email_draft` 等字段。Day 3 将进一步用
> `LeadFeatures → PolicyV1 → LeadDecision` 替换当前过渡分析结构。在完成 Day 3 前，
> n8n、CRM 和新代码不得根据本文件中的 `b2b_category` 或 `follow_up_email` 新增映射。

## 1. 文件目的

本文档用于定义 AI Lead Analysis 节点的结构化输出格式。

目标是让 AI 对销售线索的分析结果保持稳定、可机器读取，并能被后续的 n8n 工作流和 Notion CRM 数据库直接使用。

AI 输出不得是自由文本，必须符合本文档定义的字段、类型、取值范围和 JSON Schema。

## 2. AI 输出字段

| 字段名 | 类型 | 是否必填 | 允许取值 / 规则 | 什么时候为空 | 用途 |
|---|---|---:|---|---|---|
| `lead_type` | string | 是 | `B2B`, `B2C`, `Unknown`, `Spam / Low-value` | 不允许为空 | 判断 lead 的基本类型 |
| `b2b_category` | string | 是 | `Overseas Travel Agency`, `Corporate Client`, `Content Creator / Media`, `Local Partner`, `DMC / Ground Operator`, `Other B2B`, `None` | 当 `lead_type` 不是 `B2B` 时，值为 `None` | 判断 B2B lead 的子类型 |
| `intent_level` | string | 是 | `High`, `Medium`, `Low` | 不允许为空 | 判断销售跟进优先级 |
| `lead_score` | integer | 是 | 0-100，必须是整数 | 不允许为空 | 量化销售优先级 |
| `lead_summary` | string | 是 | 1-2 句话，简洁总结 | 不允许为空 | 总结 lead 的需求和价值 |
| `recommended_action` | string | 是 | 明确下一步人工跟进动作 | 不允许为空 | 给销售或运营人员提供下一步建议 |
| `follow_up_email` | string | 是 | 只能是邮件草稿，不能表示已经发送 | 如果不建议跟进，可以为空字符串 | 生成供人工审核的邮件草稿 |

## 3. 字段判断规则

### 3.1 `lead_type`

`lead_type` 用于判断 lead 的基本类型。

判断规则：

- 当 lead 明显来自公司、旅行社、机构、媒体账号、内容创作者或潜在商业合作方时，使用 `B2B`。
- 当 lead 明显来自个人游客、情侣、家庭、朋友小团体或私人旅行咨询时，使用 `B2C`。
- 当 message 主要是广告、SEO 推广、无关服务推销、垃圾信息，或没有真实旅行服务需求时，使用 `Spam / Low-value`。
- 当 message 不够清楚，但也不能明确判断为垃圾信息时，使用 `Unknown`。

### 3.2 `b2b_category`

`b2b_category` 用于细分 B2B lead。

判断规则：

- `Overseas Travel Agency`：海外旅行社寻找中国、四川、成都或西部地区的地接供应商。
- `DMC / Ground Operator`：目的地管理公司、地接操作方、receptive operator，通常提供目的地内的交通、导游、活动、线路执行、会议或团队接待等服务。
- `Corporate Client`：公司客户咨询商务旅行、奖励旅游、团队出行、商务考察、代表团接待等。
- `Content Creator / Media`：博主、影响者、记者、媒体账号或内容创作者寻求合作。
- `Local Partner`：本地供应商、酒店、车队、导游、活动方等寻求合作。
- `Other B2B`：属于 B2B，但不适合归入以上类别。
- `None`：当 `lead_type` 不是 `B2B` 时，必须使用 `None`。


### 3.3 `intent_level`

`intent_level` 用于判断跟进优先级。

判断规则：

- `High`：需求清晰，有明确目的地、服务内容、时间、人数，或具备明显商业价值。
- `Medium`：需求真实，但缺少关键细节，例如时间、人数、预算、具体目的地不清楚。
- `Low`：需求弱、信息模糊、商业价值低，或内容接近垃圾信息。

### 3.4 `lead_score`

`lead_score` 用于量化销售优先级。

规则：

- 必须是 0 到 100 之间的整数。
- 分数越高，代表越值得优先跟进。
- 高分通常需要同时具备：真实需求、明确服务内容、清晰时间线、较高商业价值。
- 垃圾信息、无关推广或低价值咨询应给低分。
- AI 不能只凭语气热情给高分，必须根据业务价值和需求清晰度判断。

### 3.5 `lead_summary`

`lead_summary` 用于简要总结 lead。

规则：

- 用 1 到 2 句话总结。
- 必须包含核心需求。
- 如果是 B2B，应说明其潜在商业价值。
- 如果是 spam 或 low-value，应说明为什么价值低。
- 不要编造原始 message 中没有的信息。

### 3.6 `recommended_action`

`recommended_action` 用于告诉人工下一步怎么处理。

规则：

- 对高价值 B2B lead，应建议优先人工跟进。
- 对 B2C lead，应建议索要缺失信息，例如日期、人数、预算、偏好。
- 对 spam 或 low-value lead，应建议不跟进或低优先级处理。
- 建议必须具体，不能写“继续联系客户”这种废话。

### 3.7 `follow_up_email`

`follow_up_email` 是邮件草稿。

规则：

- 只能作为人工审核用的草稿。
- AI 不能声称邮件已经发送。
- 不允许自动发送给客户。
- 如果不建议跟进，返回空字符串。
- 邮件语气应专业、简洁、自然。

## 4. JSON Schema

下面是 AI Lead Analysis 节点必须遵守的 JSON Schema。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "lead_type",
    "b2b_category",
    "intent_level",
    "lead_score",
    "lead_summary",
    "recommended_action",
    "follow_up_email"
  ],
  "properties": {
    "lead_type": {
      "type": "string",
      "enum": ["B2B", "B2C", "Unknown", "Spam / Low-value"]
    },
    "b2b_category": {
      "type": "string",
      "enum": [
        "Overseas Travel Agency",
        "DMC / Ground Operator",
        "Corporate Client",
        "Content Creator / Media",
        "Local Partner",
        "Other B2B",
        "None"
      ]
    },
    "intent_level": {
      "type": "string",
      "enum": ["High", "Medium", "Low"]
    },
    "lead_score": {
      "type": "integer",
      "minimum": 0,
      "maximum": 100
    },
    "lead_summary": {
      "type": "string",
      "minLength": 1
    },
    "recommended_action": {
      "type": "string",
      "minLength": 1
    },
    "follow_up_email": {
      "type": "string"
    }
  }
}
```


## 5. JSON Schema 设计说明

- `additionalProperties: false` 表示 AI 不允许输出额外字段，避免 n8n 解析出不需要的内容。
- `required` 表示所有字段都必须出现，即使某些字段没有实际内容，也要按规则返回固定值。
- `enum` 用于限制字段只能从指定选项中选择，避免 AI 自己创造新分类。
- `lead_score` 被限制为 0-100 的整数，方便后续排序、筛选和触发高分 lead 通知。
- `b2b_category` 使用字符串 `None`，而不是 null，目的是降低 n8n 和 Notion Select 字段映射复杂度。
