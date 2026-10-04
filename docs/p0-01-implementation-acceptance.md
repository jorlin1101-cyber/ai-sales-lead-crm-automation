# P0-01 开发与逐项验收记录

日期：2026-10-04。依据：[最终设计 1.0](p0-01-final-design.md)。开发副本：`D:\Python project\ai-sales-lead-crm-automation-next`。远端提交、授权与来源证据见 [GitHub 正式接纳记录](p0-01-remote-acceptance.md)。

**当前结论：两份真实 GitHub 离线产物已完成来源核验、正式基线接纳和首次主分支回归，quality、PostgreSQL、Docker 检查全部通过。26 项中 25 项通过；Q22 为尚未开展的条件性 live 实验。P0-01 的工程工具与离线基线交付完成；11 项既有业务失败仍保留，真实 AI 质量未测，本套件发布检查仍阻断。**

## 当前状态：正式离线基线与首次回归已完成

项目负责人先确认全部 22 条业务案例，再明确授权“允许公开并完成后续接纳”。首版实现已由 PR #1 合入 main；首次主分支检查发现受保护路径的 fnmatch/glob 匹配不一致，保留失败记录后通过专用修复 PR #2 受控接纳。修复没有缩小保护范围，没有把业务失败改成通过。

主分支现要求 quality、postgres、docker 三个 GitHub Actions 检查、分支保持最新和对话解决，禁止强推与删除。当前仓库采用单 owner 治理：管理员保留受控例外，必需独立人工批准数量为 0，不声称有不存在的第二名审核者。未来 live 的开放语义判分仍要求不同真人承担开发和销售两角色。

| 已完成证据 | 实际结果 |
| --- | --- |
| 正式报告来源 M0 | `83921e3d346f61340f1a2b5f626b47b85bd1a101` |
| 主分支 CI | [运行 37193943951](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/actions/runs/37193943951)，quality、postgres、docker 全部通过 |
| 全量测试与覆盖率 | M0、M2 均为 1084 passed、2 skipped，96.66%；原 95% 门槛保留 |
| PostgreSQL | 独立作业 2 passed；普通测试中的两项条件跳过没有替代实际数据库检查 |
| 保护修复验证 | 57 项定向测试通过；两个策略检查入口对 39 个受保护文件实际核验通过 |
| 实际运行环境 | Ubuntu 24.04，runner image `20260927.320.1`；Python 3.12.13、uv 0.12.0、依赖锁固定 |
| 原始报告核验 | `verify_github_artifacts()` 核对真实 GitHub 来源、ZIP 摘要、manifest 和全部封存文件字节 |
| 业务结果边界 | 11 项既有失败与 open 缺陷精确对应；执行错误及待裁定为 0，失败继续记失败 |
| 真实模型 | 未调用；真实 AI 质量和整个产品发布未评估 |

两份 M0 原始 manifest 散列：

```text
rule_only    835a9c229b1a5b683de8d20b43ee157c2507c85af374a40e87336f2e025526b4
mocked_model 48173cd71fc8c499ffa86feb828ad433af4981b2e6975e74f9c21b58dbb7d036
```

M0 的受测 SHA 和报告字节保持不变。后续 M1 只承载具体审批绑定及批准的缺陷快照，M2 承载接纳归档和两个基线指针；不能把后续保存审核材料的提交写成 M0 的受测版本。`ubuntu-latest` 仍会滚动，本次镜像版本是实际记录，不是永久锁定承诺。

| 正式接纳环节 | 实际记录 |
| --- | --- |
| M1 具体报告授权 | [专用 PR #3](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/pull/3)，可信提交 `04dbf69c50c06cdc2c78bd0471b1aa242b478739`，合并时间 `2026-10-04T10:08:20Z`；[主分支 CI 37194392517](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/actions/runs/37194392517) 全部通过 |
| M2 原子归档 | [专用 PR #4](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/pull/4)，提交 `3357a61d928868af1070ff9e57579112b0deacfc`，合并时间 `2026-10-04T10:11:39Z`；两个接纳 API 从真实 M1 信任配置回放一致，initial/accepted/latest 指针一致；16 个归档文件通过 Git blob 字节一致核验 |
| 首次正式 regression | [M2 主分支运行 37194573498](https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/actions/runs/37194573498) 的 quality、postgres、docker 全部成功；实际日志核验两个模式均为 `gate_kind=regression`、`exit_code=0`、`provisional=false`，四个阶段退出码 `[0, 0, 0, 0]`；产物复核与回执见 [远端接纳记录](p0-01-remote-acceptance.md) |
| 最终 26 项汇总 | Q01—Q21、Q23—Q26 共 25 项通过；Q22 条件性 live 实验未开展 |

## 业务确认与历史证据边界

22 条案例由项目负责人在本次会话明确回复“业务案例已确认”后登记审核状态、确认人、时间及依据，见 [业务确认记录](../config/quality_case_review.v1.json)。客户输入、正确要求、适用模式和严重度保持原内容。该确认与具体报告、缺陷豁免、基线接纳分别留证。

初始开发依据为 `7cbd8650757ca6754292542d902c4dfb7c39d7df`。首次本地实现与四份工程报告的实际受测提交为 `341c47e3c99420390099238cabd712dc14809037`，当时分支为 `codex/p0-quality-baseline`，尚未推送 GitHub、合并 main 或启用远端保护。业务确认后的本地复测提交为 `ea04c81c110a132e2567c4f9b46274c8f54804de`。这些历史报告及其临时状态均不改写，不用最新 CI 结果覆盖旧阶段发生过的情况。

## 做了什么

为销售助手增加了可重复的质量检查工具：固定22个场景，运行真实业务入口，保存系统当时的表现，再独立判断是否符合要求。新增版本与环境留证、失败案例库、中文报告、回归对照、人工复核、发布检查和CI脚本。

本阶段新增评测旁路，没有修改生产API、业务数据库结构、客户回复规则或PolicyV1。客户说8人却被采信999人、撤回需求未更新、无依据承诺仍被接受等原有问题，已被稳定记录为后续修复任务。

## 计划完成情况

1. 数据契约和22场景：已实现；原4个场景复用，新增18个场景。
2. 真实入口回放、隔离、分模式评分及旧检索/推荐契约复用：已实现并运行。
3. 不可覆盖报告、人工复核、三类门槛、双基线和可信来源校验：已实现并通过反例测试。
4. 锁定依赖 CI、命令行及操作说明：已实现，真实 CI 和主分支保护已核验；M1 授权、M2 正式接纳和首次回归闭环已完成。
5. 全量检查、数据库/容器和两轮本地离线评测：历史实测保留如下；最新真实 CI 结果以上方 M0 记录为准。

## 历史阶段 A：首次本地工程验收

| 检查 | 结果 |
| --- | --- |
| 普通测试 | 1069 passed，2 skipped；跳过项为另行执行的PostgreSQL测试 |
| 全项目覆盖率 | 96.65%，原95%门槛保留 |
| PostgreSQL | 2 passed；新建临时数据库从空库迁移到head，覆盖并发、恢复与审核 |
| Ruff / 格式 / mypy | 全部通过；206文件格式检查、87源文件类型检查 |
| 离线业务冒烟 | 通过；external_socket_connect_attempts=0 |
| Docker | 最终镜像构建成功；health/ready通过；UID=100；pip check通过 |
| 依赖 | uv.lock与requirements导出一致，容器35项共有依赖版本匹配 |
| 规则模式 | 10场景、11检查点：8通过、3业务失败；执行错误0 |
| 模拟模型模式 | 12场景、18检查点：10通过、8业务失败；执行错误0 |
| 重复运行 | 两模式各运行两次，稳定结果及环境/输入指纹一致 |
| 真实模型调用 | 0；真实AI质量未测 |
| inventory | 实际返回0；临时工程报告，保留已知业务失败 |
| release诊断 | 实际blocked、exit=3；缺正式来源、正式状态和live等原因没有被隐藏 |

Docker沿用项目已有`python:3.12-slim`，本次实际Python为3.12.15；本地/CI配置为3.12.13。依赖已核对，容器冒烟不冒充同环境质量基线。Docker图像ID：`sha256:bd08f6e94f1c2016a7d58b4ccc6c83aaf25bb8ef3003e8587f9d0799cd0769f5`。本次创建的两个最终验收容器及先前临时应用容器已清理。

完整测试首轮暴露旧CI测试仍断言宽泛Python3.12的问题，现已改为固定3.12.13并完整重跑通过。没有降低覆盖率、跳过失败项或修改业务结果来获取通过。

## 当前 26 项逐项核对

“通过”指对应工具或工程要求实测满足，不代表业务案例全部正确。已有本地测试仍作为工具能力证据；Q15、Q18、Q23、Q24 已追加真实 GitHub 验证，Q25 在 M1/M2 接纳和首次主分支回归通过后完成。

| 编号 | 验收要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| Q01 | 记录真实源码、评测器、样本、知识、提示词、配置和实际依赖指纹；未提交代码不能冒充正式基线 | 通过 | M0 两份实际 CI 报告记录真实提交、clean/reviewed/nonprovisional 状态和完整指纹，来源已核验；历史 341c47e 四份报告保留标签未审导致的 provisional=true。错安装及动态导入保护有测试覆盖。 |
| Q02 | 22 场景唯一；规则 10、模拟 12、真实 10 分开；新增探针、适配器自测和 trial 不增加场景总数 | 通过 | 最终两模式分别10/12场景；live清单10场景×3次；test_case_inventory_reuses_four_original_ids_and_has_fixed_mode_counts验证总数22，探针不增场景。 |
| Q03 | F01/G01 修复前可复现；API 和独立连接读库的值、内容、状态和来源关系可追溯；未读库不能声称已查存储 | 通过 | mocked报告F01/G01均在main、api/result、api/persisted复现失败；独立SQLite查询标记、值/内容/状态/来源比较保留。test_mocked_wrong_outputs_reach_real_api_and_independent_database。 |
| Q04 | F05 客户确认前态能更正；人工确认对照进入冲突；来源按当前消息及实际编号映射核对 | 通过 | F05离线通过；test_f05_complete_chain_preserves_human_confirmation_protection验证customer_confirmed更正及human_confirmed冲突、当前来源。 |
| Q05 | M01—M04 区分撤回与未提及；适配器没有替产品补入撤回语义；表达缺口如实失败 | 通过 | M01/M02/M03各保留1失败；M04通过。test_production_rule_path_reports_retraction_gap_without_fixing_it验证适配器未代产品撤回。 |
| Q06 | 合法近邻按正确要求判定；全拒绝不能取得高分；新增近邻未通过时如实登记 | 通过 | F03—F06、G03—G06及M04—M06按各自要求通过；正常保留、合法改写与已有保护均有对应检查器反例。拒绝所有输出不能全通过。 |
| Q07 | 模拟成功不因模板方式误判；模拟超时模板可用不等于模型成功；阶段记录和两个结论均可见 | 通过 | test_live_timeout_fallback_is_observed_as_model_error_with_business_result及test_model_stage_failure_is_independent_of_successful_template；目标模型与业务结果独立。全部使用本地替身。 |
| Q08 | 检查器对错误、合法改写、待裁定和执行故障判定正确；已有保护拒绝与基础设施故障分开 | 通过 | test_quality_checks.py覆盖错误值、合法改写、needs_review、检查器错误、保护拒绝和基础设施故障；开放语义不靠固定字面关键词自动判正确。 |
| Q09 | 原 18 查询 v4 三路径完整复用；12 推荐仅作数据契约；指标、标签和分母未被偷换 | 通过 | 最终rule报告含retrieval-v4.json的18查询/3路径与recommendation-contract.json的12数据契约；旧两组评测测试调用共享检查逻辑；原分母/grade-3标签口径保留。 |
| Q10 | 相同环境两次离线稳定结果一致；单例、整批、倒序一致；原始诊断信息未被删去 | 通过 | repeated-offline-runs.json验证两模式各2轮，稳定断言全部相同；消息ID按实测映射归一，原报告不变；检索双向比较无变化，推荐报告相同；单例/整批/倒序另有runner测试。 |
| Q11 | 环境数据库哨兵未被访问；逐例资源独立；独立 CLI 可阻断外部连接及非目标副作用 | 通过 | test_process_environment_cannot_select_database_or_live_services验证环境数据库哨兵；每case/trial/probe新SQLite；test_guard_works_in_plain_python_without_pytest_socket_plugin验证独立入口断网；真实调用0。 |
| Q12 | 重复输出目录被拒绝；半份或被改写报告不能接纳；漏项、重复、未知键、错散列得到约定错误 | 通过 | test_quality_report.py中的封存损坏/漏项/重复/未知键/错散列反例，以及CLI目录复用、中断与运行中改文件测试全通过。中断日志保留，不能冒充完成报告。 |
| Q13 | 首份 inventory 即使存在已登记 fail 也能接纳为基线，但发布仍阻断；没有初始化循环依赖 | 通过 | 最终两离线报告合并inventory实际返回0，保留11失败；bootstrap接纳单元测试允许精确登记旧缺陷，拒绝未审/执行错误；实际release诊断仍blocked。正式接纳见Q25。 |
| Q14 | FAIL→PASS→FAIL 最后一步被阻断；已解决缺陷豁免失效，新错误类型或严重度升级不能沿用旧豁免 | 通过 | test_regression_requires_precise_open_issue_and_never_waives_recurrence、test_bootstrap_advancement_resolves_issues_atomically_and_blocks_recurrence等验证FAIL→PASS→FAIL、类型/严重度变化及旧基线回退。 |
| Q15 | 普通 PR 修改答案、新评测器、旧检索计分器、豁免或必测清单不能自行放行；实际加载来源受核验，规则变化按升级流程处理 | 通过 | main 三个真实 Actions 检查、strict、禁强推/删除已启用；M0 两入口实际核验 39 个受保护文件。fnmatch/glob 缺陷经 57 项定向测试修复；专用升级 PR 保留策略阻断，再由获授权 owner 例外接纳，不冒充独立双人审核。 |
| Q16 | 人工复核只影响允许人工判分项；输出散列不符、冲突或未接纳复核不能改变有效结论 | 通过 | 复核限定原始needs_review；观察/rubric绑定、未接纳集合、冲突及同人双角色测试通过；CLI固定developer+sales，单人不能当双人。 |
| Q17 | 原始 needs_review 追加有效复核后可生成新 gate 结论，原始文件及旧 blocked 判断保持不变 | 通过 | test_reviews_can_complete_release_without_changing_sealed_evidence验证追加复核后新decision通过，原始needs_review及旧blocked文件字节保持不变。 |
| Q18 | 上传后 artifact 来源索引独立生成；原报告散列不变；自报可信、错误提交或来源不符被拒绝 | 通过 | M0 运行 37193943951 的真实 artifact 与外层来源索引已下载；verify_github_artifacts 核对实际提交、成功运行、workflow、ZIP 摘要及全部封存文件字节，两个 manifest 与本页一致。原有伪造/错摘要/错来源反例测试保留。 |
| Q19 | 缺必需模式、缺凭据、执行故障、不可比、业务退化返回约定非零；多原因按 3→2→1→0 处理 | 通过 | 报告/CLI 测试覆盖各类非零和优先级。初期临时报表 release 诊断 exit=3 保留；正式来源核验后的最新诊断 exit=2，阻断原因仅为 11 项 mandatory fail 与缺 live，没有来源错误。 |
| Q20 | release 只聚合指定候选、同协议、非 provisional 的所需报告；未测与待复核不能被删出分母 | 通过 | 发布测试验证相同候选、协议、评测器、套件、知识、环境、非provisional及完整必测集合；实际发布诊断blocked，product_release_status=not_evaluated。 |
| Q21 | 模拟验证每例三个独立 trial、各轮目标阶段实际请求次数、缓存禁用、预算耗尽及用量 unknown；没有真实调用则明确未测 | 通过 | test_live_three_trials_use_fresh_clients_and_record_actual_stage_requests验证10例×3独立trial与实际阶段请求；预算、无重试/缓存、unknown用量、超时和中断测试通过。真实模型未调用。 |
| Q22 | 真正开展 live 后逐例保存全部 trial、人工判断和用量；报告的模型质量结论仅限本次输入与配置 | 未开展：条件性实验 | 本次未开展真实模型实验，不能提供AI准确度结论。按设计这是条件性实验；手动workflow和接口隔离自测已完成，但不能替代真实模型证据。 |
| Q23 | CI 两测试作业锁定安装；容器依赖导出一致；实际环境与声明吻合，过期锁文件会失败 | 通过 | M0 quality/postgres 作业实际使用 Python 3.12.13、uv 0.12.0、uv sync --locked --extra dev；约束导出检查及 Docker 作业通过。保留本地过期锁与不一致阻断测试；记录实际 runner 镜像，不宣称完整 OS 永久固定。 |
| Q24 | 原静态检查、普通测试、覆盖率、PostgreSQL 和 Docker 要求按本次变更实际重跑并报告 | 通过 | M0 真实 GitHub CI：1084 passed、2 skipped、96.66%；PostgreSQL 另行 2 passed；quality、postgres、docker 全绿。首次本地 1069 passed/96.65% 等证据保留在历史阶段 A，不与最新运行混用。 |
| Q25 | 首份正式离线基线经过业务复核；两种模式参照、运行证据、缺陷登记和后续修复任务可对应 | 通过 | 22 条业务标准及具体接纳获真实 owner 授权；两份 M0 报告与 11 项旧失败精确核验。M1 信任绑定、M2 两个接纳单元及 initial/accepted/latest 指针已入库，归档字节一致；主分支 37194573498 首次正式回归和三个 CI 作业全部通过。 |
| Q26 | 非技术摘要能回答测了哪个版本、哪里有问题、比之前变化什么、真实 AI 有没有测、下一步修什么 | 通过 | 两模式summary.md提供实际提交、场景/失败、客户表达、正确要求、修复任务、真实AI未测和比较边界；业务复核包用产品语言解释22例；没有已接纳参照时明确不能声称质量提升。 |

## 历史阶段 A 的本地证据索引

报告均位于被Git忽略的`data/runtime/`，保留原始字节。下面路径相对于开发副本；跨设备需另外转移完整报告并重新校验，不能只复制摘要。

| 证据 | 路径 |
| --- | --- |
| 规则第1/2轮 | `data/runtime/p0-01-final-rule_only-01/`、`p0-01-final-rule_only-02/` |
| 模拟第1/2轮 | `data/runtime/p0-01-final-mocked_model-01/`、`p0-01-final-mocked_model-02/` |
| 实际盘点判断 | `data/runtime/p0-01-final-inventory-01/` |
| 实际发布阻断诊断 | `data/runtime/p0-01-final-release-blocked/` |
| 重复稳定性证明 | `data/runtime/p001-verification/repeated-offline-runs.json` |
| 测试日志 | `data/runtime/p001-verification/pytest-full.txt`、`postgresql.txt` |
| 容器证据 | `data/runtime/p001-verification/docker-final.json`、`container-dependencies.json` |
| 远端只读核对 | `data/runtime/p001-verification/github-readonly.json` |

四份manifest散列：

```text
rule_only-01  2c9e060e86b9d7c060a7ee74632dae7a50514586fbdbe5fb20b160842fc72e5a
rule_only-02  14195de64726e852dba5622a3e1e2e59f2486ac42cc51a0ba0b46a02d714acd0
mocked-01     1a6d0351239ffb6ceff298833a608002b1b9144d43777352862195aeac2a20d3
mocked-02     2040574f6cf6ec1f1f9fd11ead2b596a31cf32111575851d5818dc0b6ea69529
```

四份报告均`source_dirty=false`、`business_labels_reviewed=false`、`provisional=true`。临时状态来自标签尚待审核，不能通过改manifest消除。重复比较保留所有稳定断言字段；随机内部消息编号按每份报告中的实际外部编号映射归一，观察散列和原始观察原样保留。

## 正式接纳完成情况与发布边界

1. **已完成**：项目负责人确认 [业务复核包](p0-01-business-review-pack.md)全部 22 条期望，确认人、角色、时间和依据已记录；公开及后续正式接纳已另行明确授权。
2. **已完成**：规则已合入 GitHub main；适合单 owner 的主分支保护和受控升级方式已配置。历史 `protected=false` 只对应最初只读核对，不能作为当前状态。
3. **已完成**：M0 主分支完整 CI、两份真实离线报告的来源与字节核验，11 项旧失败的精确匹配。
4. **已完成**：M1 具体授权、M2 两模式基线与索引/信任/缺陷快照原子归档，以及 main 的第一次正式 regression 全绿。接纳 ID 分别为 `p0-01-rule_only-37193943951` 和 `p0-01-mocked_model-37193943951`，封存报告受测版本仍是 M0。
5. **条件性未开展**：若验证 AI 辅助产品发布，再显式配置模型与凭据开展 live 实验并完成两方语义复核。当前实际调用为 0；使用 M0 正式报告、M2 信任配置及真实来源索引的 release 实测返回 `exit_code=2`、`suite_release_status=blocked`、`provisional=false`，11 项 mandatory fail 和缺 live 均未豁免。诊断位于 `data/runtime/p001-github-handoff/formal-baseline-release-blocked-03/decision.json`。

具体命令见 [操作说明](p0-01-quality-operations.md)，真实 PR、来源和接纳提交以 [GitHub 正式接纳记录](p0-01-remote-acceptance.md)为准。正式基线接受已知失败以便防回退，不把失败改成业务通过，也不代表整个 P0 发布。

## 已登记的后续产品修复

| 工作 | 失败场景 | 产品含义 |
| --- | --- | --- |
| P0-03 事实与原话核验 | F01/F02，4个失败检查点 | 客户说8人，错误人数仍可能被确认 |
| P0-04 需求更正与撤回 | M01/M02/M03，3个失败检查点 | 客户撤回需求或更正身份后，旧状态未同步 |
| P0-05 承诺与证据核验 | G01/G02，4个失败检查点 | 资料未支持的确认或保证仍可能被接受 |

11 项缺陷均有固定键、错误类型、严重度及后续任务，见 `config/quality_known_issues.v1.json`。它们最初以工程观察登记，具体基线授权及快照留证见远端接纳记录；当前和后续接纳都继续计为失败，不伪造独立人工签字。

## 历史阶段 B：业务确认后的本地复测

受测提交：`ea04c81c110a132e2567c4f9b46274c8f54804de`。本次仅更新业务审核记录和对应测试/文档；执行器、评分器及生产代码未改，业务输入、预期和严重度的内容散列与被确认版本一致。

| 本次检查 | 实测结果 |
| --- | --- |
| 案例审核 | 22/22 reviewed；保留用户原话、确认前提交、原案例包散列和逐案例业务内容散列 |
| 相关测试 | 48 passed；覆盖案例库存、加载、审核字段、默认draft、真实入口和原4场景 |
| 静态检查 | Ruff通过，206文件格式检查通过 |
| rule_only | 10场景/11检查点，3个原有业务失败，0执行错误 |
| mocked_model | 12场景/18检查点，8个原有业务失败，0执行错误 |
| 新报告状态 | business_labels_reviewed=true，source_dirty=false，provisional=false |
| 审核前后对照 | 全部断言键、业务判定、错误类型、已知缺陷编号和严重度一致；源码/评分器指纹相同 |
| inventory | 实际exit=0、provisional=false |
| 发布诊断 | 仍blocked，exit=3；业务案例确认不等于CI来源或发布接纳 |
| 实际AI调用 | 0 |

新报告路径：`data/runtime/p0-01-reviewed-rule_only-01/`、`data/runtime/p0-01-reviewed-mocked_model-01/`。判断路径：`data/runtime/p0-01-reviewed-inventory-01/`、`data/runtime/p0-01-reviewed-release-blocked/`。核对证据：`data/runtime/p001-verification/business-confirmation.json`。

新manifest散列：

```text
rule_only    2964945220bbc4db653b7ffc57c677a3afde984d9f6a47fb6fbbe8b2854d7ff0
mocked_model 13ea4a789300c35a3221f4e140cff3627186bb3cd9b1231ff8618fb564d3e1c1
```

`provisional=false`说明本地运行代码与案例审核条件已满足，仍需具体报告和CI来源接纳才能成为正式基线。标签审核使套件/协议散列变化，因此本次审核前后对照是业务行为核对，不冒充对已接纳基线的正式regression。旧报告保持原样。
