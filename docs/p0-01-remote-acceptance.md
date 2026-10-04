# P0-01 GitHub 正式接纳记录

当前结论：两份正式离线基线已接纳，首次回归及全部 GitHub 检查通过。25 项验收通过，Q22 真实模型实验未开展。11 项原有业务失败仍保留，产品发布仍被阻断。完整逐项结果见 [实施验收记录](p0-01-implementation-acceptance.md)。

## 授权与边界

项目负责人在本次会话确认了 22 条业务案例，并在查看公开同步清单后明确回复：

> 允许公开并完成后续接纳

授权范围是公开代码、合成评测案例、设计与验收文档、业务确认记录，继续完成 CI、符合检查条件的合并、分支保护与正式基线接纳。该授权是仓库负责人的单人项目授权，不是两名独立人员的复核，也没有替代真实模型实验中的开发、销售双角色判分。

首版实现已通过 GitHub 的 quality、postgres、docker 检查并由 PR #1 合并。主分支已要求上述三个 GitHub Actions 检查、分支保持最新和对话解决，禁止强推、禁止删除。管理员保留受控例外权限，用于设计中规定的评分规则或基线元数据专用升级；普通代码变更继续走检查。没有将失败检查改写成成功。

## 首次主分支检查暴露的工具缺陷

- 首版受测实现：`0cfcd7bb682ee8488c51677a9f412013edac13f0`。
- [首次功能分支成功运行](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/actions/runs/37193117827)。
- [首版实现 PR #1](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/pull/1)。
- 首次合并提交：`e23900477bcde36ec39e1103628f616388172e44`。
- [首次主分支失败运行](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/actions/runs/37193310750)：可信评分规则检查将已有的 `data/rag_eval/review/bge-m3-v4-unjudged-review.json` 误判为删除。

根因是旧文件集合使用可跨目录的 `fnmatch`，当前文件集合使用不跨目录的普通 glob。同一份文件在两个集合中的匹配结果不一致。修复统一采用原有的 fnmatch 保护范围：按模式固定目录前缀枚举，再使用相同规则匹配；忽略规则不能隐藏新增受保护文件。保护范围没有缩小。

修复提交还将协议说明改为引用独立状态文件，避免基线冻结后仅为更新说明文字就改变整个协议散列。案例、期望、严重度和业务判分规则没有修改。

这次修复本身修改受保护的验收工具，因此可信旧版检查应阻断该专用升级 PR。按已批准设计中的受控升级流程处理：保留失败结果，附本地完整检查证据，由已获授权的仓库管理员执行限定于该 PR 的例外接纳；随后要求主分支完整 CI 实际通过，才允许冻结基线。不会关闭全仓库检查或使用失败运行的产物。

## 后续接纳顺序

1. 修复后主分支完整 CI 通过，取得两种离线模式的原始运行报告与上传后的外层来源索引。
2. 核对实际提交、成功运行、工作流内容、下载包散列、封存文件字节、22 条案例审核状态以及 11 项旧失败的精确登记。
3. 用专门的授权登记 PR 将报告、复核集合、缺陷快照及前序版本的散列绑定写入可信主分支。
4. 从该可信提交加载绑定，调用接纳 API，将两个首次基线、索引、信任指针、缺陷快照在同一变更中归档。
5. 主分支实际执行与正式基线的回归对照；对 26 条验收要求逐项更新。

正式接纳不把 11 项已知业务失败改成通过。它们仍对应 P0-03、P0-04、P0-05 修复任务。未开展 live，不能据此批准 AI 产品发布。

## 修复本地验收

- 路径保护相关定向测试：57 passed。
- 全量测试：1084 passed，2 skipped；两个 PostgreSQL 条件项由真实 CI 独立执行。
- 总覆盖率：96.66%，原 95% 门槛保留。
- Ruff 静态检查、206 文件格式检查及 87 源文件类型检查通过。
- 完整本地日志：`data/runtime/p001-github-handoff/policy-fix-pytest.txt`（忽略目录，仅本机留存）；后续 GitHub 全量日志提供公开运行证据。

## 正式报告来源 M0

- [评分工具修复 PR #2](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/pull/2)，修复提交 `12ee64a45f43dfecd876e9d18d05765ab044c6df`，主分支合并提交 `83921e3d346f61340f1a2b5f626b47b85bd1a101`。
- [修复 PR 的规则阻断记录](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/actions/runs/37193858175)：quality 因受保护文件升级返回 3，postgres 通过，docker 随 quality 跳过；依前述受控例外接纳，没有声称这次 PR 全绿。
- [M0 主分支正式成功运行](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/actions/runs/37193943951)：quality、postgres、docker 全部通过。
- GitHub 实测 1084 passed、2 skipped，总覆盖率 96.66%；PostgreSQL 作业另行 2 passed；Docker 健康与非 root 检查通过。
- 本次 runner 是 `ubuntu-24.04`，镜像版本 `20260927.320.1`。Python 3.12.13、uv 0.12.0 和依赖锁固定；`ubuntu-latest` 仍可能滚动，不宣称完整操作系统镜像永久固定。后续回归还需匹配报告中的环境指纹。
- 原始质量 artifact ID `11299957996`，ZIP SHA-256 `3df34c334531f31a0a11e61f8766e5972f8e53360415b1474674da24129f7d84`。
- 上传后外层来源索引 artifact ID `11300292126`，ZIP SHA-256 `8f1991a0047bd7667fefa457f9e6f16a71173a7565a2f1047e092f4d738eda63`。

M0 的协议、评测器、案例和依赖自此作为本次参照固定。之后接纳元数据分别提交，原始报告保持 M0 的实际受测 SHA。

## 具体报告与旧缺陷授权登记 M1

真实下载与来源验证已完成，两个报告均为 clean、reviewed、nonprovisional，inventory 返回 0。两份报告的 11 项失败与现有 open 缺陷逐项精确一致，执行错误和待裁定均为 0。来源包、封存文件和 manifest 均通过字节及散列核验。

[授权与具体绑定](../reports/quality/acceptance/p0-01-ci-37193943951/authorization.json)、[来源核验清单](../reports/quality/acceptance/p0-01-ci-37193943951/inspection.json)和[原始外层索引](../reports/quality/acceptance/p0-01-ci-37193943951/original-provenance-index.json)随专用授权登记 PR 保存。11 条缺陷只更新首次基线审核元数据，仍为 open，失败签名、严重度和修复任务不变。该 PR 涉及受保护的信任与缺陷文件，需要设计规定的管理员例外；不伪造普通质量检查通过。

本次授权由项目负责人明确授予，代理核验具体 CI 证据并执行。没有记录不存在的独立人工审核人；自动离线判分不套用未来 live 的双人语义复核。

## 正式基线归档 M2：提案与接纳过程

[具体报告授权 PR #3](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/pull/3) 已由受控管理员例外接纳，可信合并提交为 `04dbf69c50c06cdc2c78bd0471b1aa242b478739`。[PR 检查记录](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/actions/runs/37194316155) 精确列出两个受保护配置变更，postgres 通过；未伪造 quality 通过。

从该可信主分支验证全部 39 个受保护文件后，再次通过真实 GitHub API 核验原始 artifact。两个接纳 API 调用均成功，首次参照和最近认可参照指向相同记录：

| 模式 | 接纳 ID | manifest SHA-256 | 原始结果 |
| --- | --- | --- | --- |
| rule_only | p0-01-rule_only-37193943951 | 835a9c229b1a5b683de8d20b43ee157c2507c85af374a40e87336f2e025526b4 | 11 项：8 pass / 3 fail |
| mocked_model | p0-01-mocked_model-37193943951 | 48173cd71fc8c499ffa86feb828ad433af4981b2e6975e74f9c21b58dbb7d036 | 18 项：10 pass / 8 fail |

两个归档单元包含原始封存 run、接纳单、来源记录；完整保存在 `reports/quality/baselines/p0-01.v1/`。复制后重新加载校验，原始字节与 manifest 不变。接纳单保留 API 处理时的目录记录，并另有可迁移的 `canonical_directory`；正式索引只用仓库相对路径。

两次接纳输出的完整缺陷快照一致，已批准快照散列为 `cfd52f4c379f97393c84447e07d2a4905e82f1659ee1bcf1e0ad24c6aad25f02`。空人工复核集合采用模块固定常量；没有对自动失败进行人工覆盖。

归档、首次/最近索引、信任指针和缺陷快照通过同一专用 PR 接纳。该 PR 修改受保护索引和信任配置，因此仍需已授权的限定管理员例外。其后主分支必须实际完成两模式 regression 才算远端验收完成；归档本身不冒充回归成功。

## 接纳闭环已完成：M2 首次正式回归

[基线归档 PR #4](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/pull/4) 于 `2026-10-04T10:11:39Z` 合并，实际 main 提交为 `3357a61d928868af1070ff9e57579112b0deacfc`。PR 的 [受保护索引阻断记录](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/actions/runs/37194500219) 保留，限定管理员例外没有更改任何检查结果或全局保护。

[首次正式回归运行 37194573498](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/actions/runs/37194573498) 已全部成功：quality、postgres、docker 均通过；1084 passed、2 skipped、总覆盖率 96.66%，两项 PostgreSQL 测试在独立作业完成。真实 CI 日志中两模式均为 `gate_kind=regression`、`exit_code=0`、`provisional=false`，汇总为 `[0,0,0,0]`。这次是对已接纳基线的实际比较，不再是首次盘点。

独立复核还使用 M1 的真实 trust 重放两个接纳 API，输出与接纳单一致；16 个归档文件与提交中的 Git blob 完全相同，12 个封存文件与再次从 GitHub 下载的原始 ZIP 完全相同。initial、accepted 和最新信任指针一致，已知缺陷快照保持 11 项 open。

M1 在 `2026-10-04T10:08:20Z` 合并，其 [主分支 CI 37194392517](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/actions/runs/37194392517) 也全部通过。评分口径 M0、授权 M1、接纳 M2 三个版本分别记录，避免自引用和错误改写受测提交。

正式接纳后的 [发布阻断诊断](../reports/quality/baselines/p0-01.v1/verification/release-M0-after-acceptance/decision.json) 对 M0 的两份报告重新验证真实来源；结果为 `exit_code=2`、`suite_release_status=blocked`、`provisional=false`。原因是 11 项必需业务断言失败和缺少 live，不再是临时报告或来源未认证。真实模型调用仍为 0，整个产品发布仍为 `not_evaluated`。

因此 P0-01 的 25 项非条件性验收已完成；Q22 属于尚未开展的真实模型条件性实验，不能标为通过。后续产品修复继续处理 P0-03 的事实核验、P0-04 的更正撤回、P0-05 的承诺证据；本次没有声称这 11 项产品缺陷已修复。

原始首次回归 decision 已另行归档：[规则模式](../reports/quality/baselines/p0-01.v1/verification/regression-37194573498/rule_only/decision.json)、[模拟模型模式](../reports/quality/baselines/p0-01.v1/verification/regression-37194573498/mocked_model/decision.json)。两者相对首次和最近认可基线的变化数均为 0；规则模式的检索报告可比且无逐查询退化。[治理审计记录](../reports/quality/baselines/p0-01.v1/verification/governance.json)保存实际保护配置及专用接纳的合并记录。

[最终回归核验收据](../reports/quality/baselines/p0-01.v1/verification/regression-37194573498/receipt.json)记录实际 artifact 摘要、decision 散列、环境与全部比较指纹；两模式环境清单均与 M0 相同。[对应分支保护快照](../reports/quality/baselines/p0-01.v1/verification/regression-37194573498/branch-protection.json)一并保存。网络下载重试与本地审计位置保留在收据中；最终使用实际下载字节和当次 GitHub 元数据完成核验，没有模拟远端产物。
