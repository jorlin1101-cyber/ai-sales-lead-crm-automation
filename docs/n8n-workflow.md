# n8n 工作流说明

## 当前实现

`n8n/ai-sales-lead-routing.json` 是停用状态的安全导入骨架，不包含密钥、真实客户或生产连接器。
目前只有手动触发和合成示例输入；不是已经连接真实邮箱、自动写入 Notion 的运行实例。

工作流调用 `POST /process-lead`，先检查 HTTP 状态和输入有效性，再按服务端返回的处置建议分流。
业务评分只在 Python 服务中计算，n8n 不复制评分规则。

| 分支 | 条件 | 下游 |
| --- | --- | --- |
| API Error | 非成功 HTTP 响应、请求错误 | 安全日志，不进入 CRM |
| Invalid | HTTP 成功但领域校验失败 | 安全日志，不进入 CRM |
| Suppressed | disposition=spam | 安全日志，不进入 CRM |
| Manual Review | needs_review=true 或 disposition=manual_review | 安全日志，等待人工处理 |
| High / Medium / Low | 通过上述安全门后的有效线索 | 待审核 payload 与日志 |

垃圾及人工复核判断优先于意向等级。不能把垃圾线索当作普通低意向客户跟进。

## 人工确认与 Notion

`CRM Connector Placeholder` 仍是 noOp 占位节点，不会实际写入。
真实写入应通过本服务的审核接口完成，而不是直接在该节点接一个无审核的创建页面动作：

1. 保存 `/process-lead` 返回的 `analysis_id`。
2. 由操作员核对输入、编辑回复、确认来源授权。
3. 单轮请求 `POST /crm/notion/leads`，提供保存的分析编号、未改动原始输入和审核稿。
4. 多轮请求先完成草稿审核，再调用 `POST /crm/notion/conversations/{id}`，提供草稿 ID 和版本。
5. 由后端执行权限校验、结果持久化、去重、Notion 版本核对。

占位分支的 `awaiting_human_approval` 不表示“已写入”。Notion 连接步骤见 [Notion CRM](notion-crm.md)。

## 导入注意

- JSON 内默认 API 地址为 `http://127.0.0.1:8000`，仅适用于同一网络空间。容器内 n8n 的回环地址不是宿主机。
- 网络部署请配置 `SERVICE_ACCESS_MODE=protected`，通过 n8n 凭据管理提供 Bearer 令牌，不能把令牌写入公开 JSON。
- 原始字段使用 `company_name`；旧输入 `company` 经 Normalize 节点转换。
- 日志只输出请求编号、线索编号、路由与策略版本，不输出邮件正文和访问令牌。
- 四个合成示例并未覆盖所有七个分支，须额外验证垃圾、人工复核与 HTTP 错误。
- 启用真实触发器前，需要对应平台的适配、官方签名校验、来源授权与频率控制。标准 HMAC 入站端点不能直接冒充 Gmail/企业微信官方 webhook。

## 复核

`tests/test_n8n_workflow.py` 检查七路拓扑、错误/抑制分支隔离、凭据缺失和合成数据安全性。
`scripts/review_routing.cjs` 在本地执行分类节点代码，验证垃圾、人工复核、三个等级、无效输入及 HTTP 错误。
这些检查不替代在 n8n 测试实例中导入工作流并联调真实连接器。
