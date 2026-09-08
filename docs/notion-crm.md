# Notion CRM 接入指南

## 业务流程

```text
原始线索
  -> POST /process-lead
  -> 页面展示决策、建议和依据
  -> 销售人员编辑邮件并确认数据来源合法
  -> POST /crm/notion/leads
  -> 后端读取 Notion 数据源字段
  -> 按稳定线索编号查询是否已存在
  -> 返回已有记录，或创建新的 CRM 页面
  -> 页面显示 Notion 记录链接
```

系统不会把 `NOTION_API_KEY` 发送到浏览器。首次分析返回 `analysis_id`，服务器持久化该次分析。
确认写入时，浏览器提交该编号、未改动的原始输入以及人工确认稿；后端读取保存的分析快照，
不重新调用模型。如果输入变化或记录不属于当前访问身份，则拒绝写入。审计身份来自服务端鉴权，
不是页面自由填写的确认人。所有 Notion 请求由后端发出。

多轮会话使用 `POST /crm/notion/conversations/{conversation_id}`，提交 `draft_id` 和
`expected_version`。只有最新轮次的 `approved` / `sent` 草稿允许同步。每个同步版本持久化为
工作流事件；相同版本再次提交直接返回记录结果。新版本更新同一客户页，并保留销售人员的 CRM 阶段。

## 1. 创建集成并授权

1. 在 Notion 的集成管理页创建一个内部集成，复制 Internal Integration Secret；
2. 新建一个数据库，建议命名为 `AI Sales Leads CRM`；
3. 打开该数据库的连接设置，把刚创建的集成添加为连接；
4. 从 Notion API 或页面信息中取得该数据库对应的 **data source ID**。

Notion 2025-09-03 版本开始区分 database 和 data source；本项目创建页面时使用
`parent.data_source_id`，不是旧版的 `database_id`。

## 2. 数据库字段

数据库必须有一个 `title` 类型字段，字段名称不限，并且必须创建 `rich_text` 类型的“线索编号”字段，
它是防止浏览器重复提交、网络重试造成重复客户记录的幂等键。推荐字段如下。
后端同时兼容表中的英文名、snake_case 名和中文名；没有创建的可选字段会自动跳过，完整
分析内容仍会写进 Notion 页面正文。

| 建议中文字段 | 类型 | 可识别别名 |
| --- | --- | --- |
| 线索名称 | Title | 任意名称均可 |
| 线索编号 | Text | `Lead ID`, `lead_id` |
| 邮箱 | Email | `Email`, `email` |
| 公司 | Text | `Company`, `company` |
| 来源 | Select | `Source`, `source` |
| 意向等级 | Select | `Intent`, `intent_level` |
| 线索评分 | Number | `Score`, `lead_score` |
| 处置建议 | Select | `Disposition`, `disposition` |
| 需要复核 | Checkbox | `Needs Review`, `needs_review` |
| 状态 | Select | `Status`, `status` |
| 处理时间 | Date | `Processed At`, `processed_at` |

每条页面正文还会保存原始留言、线索摘要、建议动作、评分拆解、人工复核原因、跟进邮件草稿、
知识来源、策略版本、确认人和确认时间。

## 3. 配置环境变量

复制 `.env.example` 为 `.env`，填写：

```dotenv
ALLOW_NETWORK=true
NOTION_CRM_ENABLED=true
NOTION_API_KEY=secret_xxx
NOTION_LEADS_DATA_SOURCE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
NOTION_API_VERSION=2025-09-03
```

`.env` 已被 Git 忽略。不要把真实令牌写进 `.env.example`、README、前端 JavaScript、截图或
n8n 导出文件。

## 4. 验证

重新启动服务后打开首页。顶部 Notion 指标应从 `OFF` 变为 `ON`，写入区域应显示连接正常。
也可以只检查安全状态接口：

```text
GET /crm/notion/status
```

随后分析一条线索，在页面中修改邮件草稿，勾选“人工核对与合法来源确认”，再点击“写入
Notion CRM”。后端保存该次分析快照和销售人员最终确认稿。相同已审核版本再次提交不会重复写入。

Notion 查询、读取和限流请求会按 `Retry-After` 安全重试；创建页面属于非幂等操作，遇到结果
不确定的网络或服务端故障时不会盲目重放。操作者可以再次点击写入，下一次请求会先通过稳定
线索编号及 `Sync Version` 标记核对记录；找不到准确版本时返回待人工核对状态，不自动重新创建。
这是持久化的同步任务记录与结果核对，不是已经配置好后台工作进程的自动队列。Notion 官方说明每个连接平均允许每秒 3 个请求，集成应处理 429 和
`Retry-After`：[Request limits](https://developers.notion.com/reference/request-limits)。

## 5. 生产环境建议

- 在反向代理或网关层为写入接口增加登录鉴权；
- 使用平台 Secret 管理环境变量；
- 将“线索编号”设为必备字段，并定期检查异常重复项；
- 当前服务端使用单工作区 `operator` 身份；正式团队使用前接入企业用户身份和细粒度角色权限；
- 保留 Notion 页面链接与 request ID 作为审计索引。
