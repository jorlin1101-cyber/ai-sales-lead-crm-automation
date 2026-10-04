# P0-01 开发与逐项验收记录

日期：2026-10-04。依据：[最终设计1.0](p0-01-final-design.md)。开发副本：`D:\Python project\ai-sales-lead-crm-automation-next`。

**结论：本地工程开发与可执行验收完成；正式业务基线尚未接纳。26项中22项通过，2项部分通过，1项条件性实验未开展，1项待业务复核与CI冻结。**

开始代码：`7cbd8650757ca6754292542d902c4dfb7c39d7df`。最终实现及实际离线受测提交：`341c47e3c99420390099238cabd712dc14809037`。随后仅补充验收文档，报告中的受测SHA不改写。分支：`codex/p0-quality-baseline`，已保存本地提交；本次未推送GitHub、未合并main、未修改远端仓库规则。

## 做了什么

为销售助手增加了可重复的质量检查工具：固定22个场景，运行真实业务入口，保存系统当时的表现，再独立判断是否符合要求。新增版本与环境留证、失败案例库、中文报告、回归对照、人工复核、发布检查和CI脚本。

本阶段新增评测旁路，没有修改生产API、业务数据库结构、客户回复规则或PolicyV1。客户说8人却被采信999人、撤回需求未更新、无依据承诺仍被接受等原有问题，已被稳定记录为后续修复任务。

## 计划完成情况

1. 数据契约和22场景：已实现；原4个场景复用，新增18个场景。
2. 真实入口回放、隔离、分模式评分及旧检索/推荐契约复用：已实现并运行。
3. 不可覆盖报告、人工复核、三类门槛、双基线和可信来源校验：已实现并通过反例测试。
4. 锁定依赖CI、命令行及操作说明：本地完成；远端保护与真实CI仍待正式接纳。
5. 全量检查、数据库/容器和两轮离线评测：已实际执行，结果如下。

## 本次实际结果

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

## 26项逐项核对

“通过”指对应工具或工程要求实测满足，不代表业务案例全部正确；正式业务接纳单独由Q25判断。

| 编号 | 验收要求 | 状态 | 证据 |
| --- | --- | --- | --- |
| Q01 | 记录真实源码、评测器、样本、知识、提示词、配置和实际依赖指纹；未提交代码不能冒充正式基线 | 通过 | 4份最终manifest记录提交341c47e、source_dirty=false、标签未审导致provisional=true；提示词与独立输出schema散列、有效设置、依赖和模块加载路径齐全；test_quality_loaded_sources.py覆盖错安装及动态导入。 |
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
| Q15 | 普通 PR 修改答案、新评测器、旧检索计分器、豁免或必测清单不能自行放行；实际加载来源受核验，规则变化按升级流程处理 | 部分通过：远端待启用 | 可信目标分支评分核验、旧计分器/规则变化阻断、实际加载目录核验及旧ref拒绝已通过测试。GitHub只读确认main protected=false且rulesets为空；远端强制审查和升级授权流程尚未启用。 |
| Q16 | 人工复核只影响允许人工判分项；输出散列不符、冲突或未接纳复核不能改变有效结论 | 通过 | 复核限定原始needs_review；观察/rubric绑定、未接纳集合、冲突及同人双角色测试通过；CLI固定developer+sales，单人不能当双人。 |
| Q17 | 原始 needs_review 追加有效复核后可生成新 gate 结论，原始文件及旧 blocked 判断保持不变 | 通过 | test_reviews_can_complete_release_without_changing_sealed_evidence验证追加复核后新decision通过，原始needs_review及旧blocked文件字节保持不变。 |
| Q18 | 上传后 artifact 来源索引独立生成；原报告散列不变；自报可信、错误提交或来源不符被拒绝 | 部分通过：真实CI待验证 | 来源writer与真实GitHubAPI适配器的离线测试通过：上传后外层索引不改原报告；空输出、错提交、错digest、伪造archive及workflow不符均拒绝。尚未在GitHub真实运行/上传，不标远端端到端通过。 |
| Q19 | 缺必需模式、缺凭据、执行故障、不可比、业务退化返回约定非零；多原因按 3→2→1→0 处理 | 通过 | 报告/CLI测试覆盖3→2→1→0优先级、缺凭据、必需模式、故障/不可比及全部原因；实际缺正式来源与live的release诊断exit=3，17条原因保留。 |
| Q20 | release 只聚合指定候选、同协议、非 provisional 的所需报告；未测与待复核不能被删出分母 | 通过 | 发布测试验证相同候选、协议、评测器、套件、知识、环境、非provisional及完整必测集合；实际发布诊断blocked，product_release_status=not_evaluated。 |
| Q21 | 模拟验证每例三个独立 trial、各轮目标阶段实际请求次数、缓存禁用、预算耗尽及用量 unknown；没有真实调用则明确未测 | 通过 | test_live_three_trials_use_fresh_clients_and_record_actual_stage_requests验证10例×3独立trial与实际阶段请求；预算、无重试/缓存、unknown用量、超时和中断测试通过。真实模型未调用。 |
| Q22 | 真正开展 live 后逐例保存全部 trial、人工判断和用量；报告的模型质量结论仅限本次输入与配置 | 未开展：条件性实验 | 本次未开展真实模型实验，不能提供AI准确度结论。按设计这是条件性实验；手动workflow和接口隔离自测已完成，但不能替代真实模型证据。 |
| Q23 | CI 两测试作业锁定安装；容器依赖导出一致；实际环境与声明吻合，过期锁文件会失败 | 通过 | 实际uv锁定安装完成；两个CI作业固定Python3.12.13/uv0.12.0并使用--locked；容器constraints导出完全一致；过期锁/不一致阻断测试通过；容器35项共有依赖与本地锁一致。 |
| Q24 | 原静态检查、普通测试、覆盖率、PostgreSQL 和 Docker 要求按本次变更实际重跑并报告 | 通过 | 本次最终1069普通测试通过、2项PG在普通套件按条件跳过后单独全部通过；总覆盖率96.65%；Ruff/格式/mypy87源文件、原离线smoke、迁移与最终Docker健康/就绪/非root验收通过。 |
| Q25 | 首份正式离线基线经过业务复核；两种模式参照、运行证据、缺陷登记和后续修复任务可对应 | 待完成：业务复核与CI冻结 | 22标签仍draft，尚无业务审核签字；两模式正式initial/accepted索引为空。已交付4份临时工程报告、11项精确缺陷、修复任务和业务复核包；不得把这些改名当正式业务基线。 |
| Q26 | 非技术摘要能回答测了哪个版本、哪里有问题、比之前变化什么、真实 AI 有没有测、下一步修什么 | 通过 | 两模式summary.md提供实际提交、场景/失败、客户表达、正确要求、修复任务、真实AI未测和比较边界；业务复核包用产品语言解释22例；没有已接纳参照时明确不能声称质量提升。 |

## 本地证据索引

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

## 需要完成的正式接纳条件

1. 按[业务复核包](p0-01-business-review-pack.md)确认22条期望，记录真实复核人、角色、时间和依据。
2. 在GitHub接纳规则、配置适合实际协作方式的分支保护和受控升级流程，再运行真实CI。只读核对显示main当前protected=false、rulesets为空。
3. 在一致CI环境重新生成两种离线报告，审核11项旧缺陷并接纳首份正式initial/accepted基线。
4. 如需验证AI辅助产品发布，再显式配置模型与凭据开展live实验，并完成两方人工复核。P0-01工程实现不要求当场付费调用模型，但缺live的发布检查应阻断。

具体命令、信任字段与基线推进方法见[操作说明](p0-01-quality-operations.md)。不能把本次本地通过、草稿案例或模拟调用替代上述条件。

## 已登记的后续产品修复

| 工作 | 失败场景 | 产品含义 |
| --- | --- | --- |
| P0-03 事实与原话核验 | F01/F02，4个失败检查点 | 客户说8人，错误人数仍可能被确认 |
| P0-04 需求更正与撤回 | M01/M02/M03，3个失败检查点 | 客户撤回需求或更正身份后，旧状态未同步 |
| P0-05 承诺与证据核验 | G01/G02，4个失败检查点 | 资料未支持的确认或保证仍可能被接受 |

11项缺陷均有固定键、错误类型、严重度及后续任务，见`config/quality_known_issues.v1.json`。这是工程观察登记，尚未伪造业务签字；它们继续计为失败。
