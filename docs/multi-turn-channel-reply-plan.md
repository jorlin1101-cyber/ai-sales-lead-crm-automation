# 多渠道、多轮销售回复执行方案

## 目标

把当前“一条线索一次分析”的流程升级为：

```text
渠道消息
  -> 渠道适配器
  -> 统一消息契约
  -> 会话与历史上下文
  -> 当前轮次分析与政策判断
  -> 渠道格式化回复草稿
  -> 人工审核
  -> 可选发送 / CRM 投影
```

核心原则：

1. 渠道决定回复格式，业务决策不因渠道改变；
2. 历史上下文只能补充已确认事实，不能让模型直接改写评分或处置结论；
3. 每条消息和每个会话都可幂等重放，重复 webhook 不得重复创建记录或发送回复；
4. 当前版本继续只生成草稿，发送能力必须经过人工审核和渠道授权；
5. Notion 是 CRM 展示和协作层，不作为高并发会话的唯一事实源。

## 一、渠道与回复格式

### 1. 统一渠道枚举

将现有 `source` 拆为两个概念：

- `channel`：决定输入解析方式和输出格式；
- `source`：记录具体来源，例如 `website_contact_form`、`gmail`、`wechat`、`linkedin`。

建议的 `channel`：

| channel | 输入示例 | 输出草稿 |
| --- | --- | --- |
| `email` | 主题、正文、Message-ID、In-Reply-To | `subject` + 纯文本正文，后续可增加 HTML |
| `web_chat` | 网站会话消息 | 简短分段文本，可带按钮或下一步问题 |
| `social_dm` | LinkedIn、Instagram 等私信 | 短文本，避免长段落和邮件主题 |
| `wechat` | 微信客服或企微消息 | 中文短消息，按问题逐点回复 |
| `sms` | 短信 | 极短文本和明确 CTA |
| `api` | 外部系统 webhook | 结构化 JSON，同时提供 `display_text` |
| `manual` | 销售人员录入 | 默认采用工作台对话格式 |

不要让大模型自行决定输出格式。后端根据 `channel` 选择确定性模板，再把已批准的知识依据和业务事实填入模板。

### 2. 回复契约

统一内部模型 `ReplyDraft`，再由渠道渲染器输出：

```json
{
  "channel": "email",
  "conversation_id": "conv_123",
  "turn_number": 2,
  "status": "needs_human_review",
  "subject": "Re: 川西定制行程需求确认",
  "body_text": "您好……",
  "body_html": null,
  "display_text": "您好……",
  "cta": "请确认预计出行日期和预算范围",
  "source_ids": ["chunk_aaa055..."],
  "policy_version": "policy-v1",
  "draft_version": 1
}
```

其中：

- `subject` 仅对 email 有效；
- `body_html` 初期保持为空，避免未经审核的 HTML 注入和样式问题；
- `display_text` 用于工作台预览；
- `source_ids` 只引用本轮实际检索到的知识片段；
- `status` 必须经过人工审核才可进入发送状态。

## 二、多轮上下文模型

### 1. 为什么不能只把历史消息拼到 prompt

直接拼接全部历史消息会造成上下文膨胀、隐私暴露、旧信息覆盖新信息，以及重复 webhook 造成重复回复。应保存结构化事实和消息审计，而不是把数据库当作一个无限长聊天记录。

### 2. 建议的数据模型

P0 已以 PostgreSQL 作为部署事实源，并保留 SQLite 作为本地/CI 兼容后端：

```text
conversations
  id
  external_conversation_id
  channel
  source
  customer_key_hash
  state
  context_summary
  created_at
  updated_at

conversation_messages
  id
  conversation_id
  external_message_id       unique(channel, external_message_id)
  direction                 inbound / outbound
  raw_text
  normalized_text
  received_at
  turn_number
  processing_status

conversation_facts
  conversation_id
  fact_key                  travel_date / group_size / budget / destination
  fact_value
  confidence
  provenance_message_id
  confirmation_status       inferred / customer_confirmed / human_confirmed / conflicted
  updated_at

analysis_runs
  id
  conversation_id
  message_id
  decision_snapshot
  retrieved_source_ids
  policy_version
  model_metadata
  created_at

reply_drafts
  id
  conversation_id
  message_id
  channel
  draft_version
  subject
  body_text
  body_html
  review_status              pending / approved / rejected / superseded
  reviewer_id
  reviewed_at

rag_retrieval_runs
  id
  conversation_id
  message_id
  decision                  required / skipped / blocked
  queries
  retrieval_method
  status

rag_retrieval_hits
  id
  retrieval_run_id
  chunk_id
  source_title
  section
  rank

reply_draft_sources
  draft_id
  retrieval_hit_id
  citation_order

delivery_events
  id
  draft_id
  provider_message_id
  status                     not_sent / queued / sent / failed
  idempotency_key
  created_at
```

### 3. 上下文读取规则

每轮只向分析链路提供：

1. `context_summary`：由已确认事实生成的短摘要；
2. 当前消息；
3. 最近 4～6 条消息，用于理解指代和语气；
4. 最近一次未解决的问题；
5. 本轮检索到的知识片段。

旧事实只作为候选事实使用。若新消息明确说“改成 12 人”或“日期改为 10 月”，新消息覆盖旧事实；如果出现无法判断的冲突，则设置 `conflicted` 并转人工复核，不能静默覆盖。

## 三、两轮示例

### 第 1 轮

客户：

> 我们公司想安排川西定制行程，大概 8 个人，想了解价格。

系统保存：

```text
customer_kind = agency              inferred
group_size = 8                       customer_confirmed
destination = Western Sichuan        inferred
asks_for_price = true                inferred
missing = travel_date, budget, special_requirements
state = waiting_customer
```

系统生成：

- email：带主题的正式邮件草稿；
- web_chat：简短说明并直接询问缺失信息；
- social_dm：更短的确认问题；
- 工作台：显示事实来源、评分、知识依据和待审核草稿。

### 第 2 轮

客户：

> 日期是 10 月 3 日到 7 日，预算每人 5000 元，没有特殊饮食要求。

系统读取第 1 轮上下文，合并新事实：

```text
travel_date = 2026-10-03 to 2026-10-07   customer_confirmed
budget = CNY 5000 per person             customer_confirmed
special_requirements = none               customer_confirmed
group_size = 8                            carried_forward
```

然后重新检索价格、日期和资源可用性知识，生成与渠道匹配的第 2 轮回复。第 2 轮不会重新猜测客户身份，也不会把 RAG 结果直接写成最终承诺。

## 四、API 设计

### 1. 保留旧接口

`POST /process-lead` 保持兼容，用于单次演示、批处理和 n8n 旧工作流。没有 `conversation_id` 时，不进入多轮状态机。

### 2. 新增会话接口

```text
POST /conversations/messages
```

请求重点字段：

```json
{
  "channel": "email",
  "source": "gmail",
  "external_conversation_id": "thread-abc",
  "external_message_id": "<message-id@example.com>",
  "in_reply_to": "<previous-message@example.com>",
  "sender": {"name": "李明", "email": "li.ming@example.com"},
  "message": {"subject": "Re: 川西行程", "text": "日期是……"},
  "source_authorized": true
}
```

响应返回：

```text
conversation_id
turn_number
current_analysis
confirmed_facts
open_questions
reply_draft
requires_human_review
idempotency_status
```

建议配套接口：

```text
GET  /conversations/{conversation_id}
GET  /conversations/{conversation_id}/timeline
POST /conversations/{conversation_id}/drafts/{draft_id}/approve
POST /conversations/{conversation_id}/drafts/{draft_id}/reject
POST /conversations/{conversation_id}/close
```

`approve` 只批准指定版本的草稿；草稿被编辑后版本号必须递增，旧版本不能被误发送。

## 五、Notion 与 CRM 的职责边界

Notion 继续作为销售人员可读的 CRM 投影：

- Leads 页面保存当前客户摘要、当前阶段、最新评分和最新草稿；
- Conversation Turns 子数据库保存每轮的时间、渠道、问题摘要、回复状态和来源编号；
- 不把完整敏感原文无限追加到 Notion；需要保存时按保存期限和权限策略处理；
- `conversation_id`、`external_message_id` 和 `draft_version` 作为幂等与审计字段；
- 写入前仍需人工确认来源合法，Notion API Key 只在后端使用。

高并发下，消息接收、分析和发送应由数据库加队列协调，不能让 Notion 同时承担锁、队列和事实源。

## 六、实现分期

### P0：可演示的多轮闭环（已实现）

1. 增加 `channel`、`conversation_id`、`external_message_id` 和 `turn_number` 契约；
2. 实现 PostgreSQL 会话存储、Alembic 迁移、事务化轮次分配和唯一幂等约束；
3. 实现 email、web_chat、social_dm 三个回复渲染器；
4. 实现结构化事实合并和冲突转人工；
5. 新增 `/conversations/messages`，保留 `/process-lead`；
6. 工作台增加会话时间线、当前事实、未解决问题、草稿和引用依据；
7. RAG 查询带入当前消息、已确认事实和近期对话，确认类短消息跳过检索；
8. 持久化检索运行、Top 3 命中和“证据—草稿”关系；
9. 用离线样例验证两轮上下文、重复消息、冲突升级、应用重启和证据链行为。
10. 识别产品、行程、报价与证件/付款意图，使用命中正文生成渠道化回复；
11. 报价知识不存在固定金额时只解释核价规则并追问必要变量，不生成虚构报价；
12. 草稿只绑定实际写入回复的证据，前端不展示未被引用的检索命中。

### P1：CRM 与审核流程

1. Notion 增加会话摘要和轮次投影；
2. 审核动作记录登录用户、时间、版本和理由；
3. 增加关闭会话、拒绝联系和退订状态；
4. 增加邮件草稿的纯文本预览和格式校验；
5. 增加 webhook 签名校验和来源授权配置。

### P2：真实渠道发送

1. 接入邮件 provider、网站实时聊天和企业微信等适配器；
2. 使用 outbox + 队列保证“审核后发送一次”；
3. 保存 provider message ID，处理超时、重复事件和退信；
4. 加入频率限制、抑制名单、退订和人工接管；
5. 增加多租户、权限隔离、保存期限和删除流程。

## 七、评测方案

已建立 `data/evals/multi_turn_conversations.jsonl`，覆盖单轮产品/证件问答与多轮报价场景；
`tests/test_conversation_eval.py` 会校验事实继承、业务意图、关键答案、生成方式和证据子集关系。

### 自动指标

| 指标 | 含义 |
| --- | --- |
| channel_format_pass_rate | 回复是否符合 email / chat / DM 等格式契约 |
| message_idempotency_rate | 重复消息是否只生成一个处理结果 |
| fact_carryover_accuracy | 第 2 轮是否正确继承第 1 轮事实 |
| conflict_escalation_recall | 冲突信息是否正确转人工 |
| grounded_source_precision | 回复引用是否来自本轮 Top 3 来源 |
| open_question_recall | 是否继续追问真正缺失的信息 |
| opt_out_suppression_rate | 明确拒绝联系后是否停止跟进 |
| draft_approval_integrity | 未审核草稿是否无法进入发送流程 |

### 人工抽检维度

- 是否理解上一轮上下文；
- 是否区分客户确认事实和模型推断；
- 是否有渠道不适配的语气或长度；
- 是否做出未经知识依据支持的价格、日期或资源承诺；
- 是否在冲突、退订、提示词注入时及时交给人工。

每次修改模板、策略或检索器，都应同时跑单轮回归和多轮回归，不能只看模型主观效果。

## 八、最终验收标准

以下条件全部满足后，才把多轮功能标记为可演示：

- 同一 `external_message_id` 重复提交不会产生第二个轮次；
- 第 2 轮能继承已确认事实，新事实有来源，冲突事实进入人工复核；
- email、web_chat、social_dm 返回不同且可读的格式；
- 当前 P0 只生成待复核草稿，不包含真实渠道发送；
- 审核、拒绝、退订与发送抑制属于 P1/P2，接入真实发送渠道前必须实现；
- RAG 来源只来自本轮检索结果，策略评分仍由确定性策略产生；
- 已启用 Notion CRM 时，写入使用业务幂等键避免重复客户页面；
- 全量测试、离线评测、静态检查和脱敏日志检查均通过。
