# P0-01 质量评测操作说明

适用版本：`p0-01.v1`；发布检查清单：`p0-01-ai-assisted.v1`。本文描述当前代码接口，设计依据见 [最终方案](p0-01-final-design.md)，本次交付状态见 [实施验收记录](p0-01-implementation-acceptance.md)。

## 1. 先确认当前状态

当前已提供两种离线运行、隔离执行、封存报告、人工复核集合、三个门槛、基线接纳 API 和真实模型手动 workflow。它们是工程能力，不构成业务批准。

当前 22 条业务标签仍待正式审核，基线索引尚未初始化，信任配置为 `bootstrap_pending`。远端 `main` 分支保护尚未启用，管理员正式接纳流程尚待完成。本次实施没有调用真实模型 API，也没有形成真实 AI 质量结论。`provisional=true` 的工程报告不能接纳为正式基线或用于发布。

推荐顺序是：先运行两种离线模式并查看缺陷 → 审核 22 条案例及判分要求 → 受控接纳首版规则 → 在固定 CI 环境重跑 → 审核并冻结两个离线基线 → 日常检查回归 → 按需执行真实模型实验与人工复核 → 对指定候选运行本套件发布检查。

## 2. 本地运行及查看报告

从仓库根目录执行。依赖使用项目锁文件；当前 CI 固定 Python `3.12.13` 和 uv `0.12.0`：

```powershell
uv sync --locked --extra dev
$qualityStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$candidateSha = (git rev-parse HEAD).Trim()

uv run --no-sync python scripts/run_quality_eval.py run --mode rule_only --out "data/runtime/quality-runs/$qualityStamp-rule"
uv run --no-sync python scripts/run_quality_eval.py run --mode mocked_model --out "data/runtime/quality-runs/$qualityStamp-mocked"

uv run --no-sync python scripts/run_quality_eval.py check --gate inventory --run "data/runtime/quality-runs/$qualityStamp-rule" --run "data/runtime/quality-runs/$qualityStamp-mocked" --candidate-sha $candidateSha --review-set empty --out "data/runtime/quality-decisions/$qualityStamp-inventory"
```

`rule_only` 覆盖 10 个场景；`mocked_model` 覆盖 12 个场景。两者不调用真实模型。`run` 返回 0 只表示适用断言已执行并完成封存；业务失败仍保留在报告中。源码未提交或标签未审核时，使用真实 HEAD 记录受测版本并标记临时状态，不能把它解释为该提交的正式基线。

先读运行目录的 `summary.md`，再按场景查看 `assertions.jsonl` 和 `observations.jsonl`。精确断言键是 `mode / case_id / probe_id / checkpoint / assertion_id / trial_id`，其中 trial 是字符串。规则模式另有 18 条检索查询的完整 v4 子报告和 12 条推荐数据契约报告；它们不与业务场景合成一个“总准确率”。

| 文件或目录 | 用途 |
| --- | --- |
| `manifest.json` | 协议、源码、环境等指纹及文件大小、散列 |
| `observations.jsonl` | 实际输入、流程观察、模型阶段及调用记录 |
| `assertions.jsonl` | 执行状态与业务判定，保留失败和未测 |
| `summary.md` | 封存当时的中文说明及待处理问题 |
| `retrieval-v4.json`、`recommendation-contract.json` | 规则模式的既有子报告 |
| `COMPLETED` | manifest 散列；证明封存完成，不证明业务通过 |
| 相邻的 `<运行目录名>.diagnostics/events.jsonl` | 开始、阶段、异常或中断诊断 |
| 独立 decision 目录 | `decision.json`、`comparison.json`、新的 `summary.md` |

运行目录、诊断目录及指定的 decision 目录都应使用新名字。重用名字会失败；不要通过覆盖报告来重试。中断后保留原目录作诊断，选择新目录重新运行。没有有效 `COMPLETED` 的目录不能参加正式比较。封存目录内也不能放新增审核备注，否则精确文件集合校验会拒绝它。

## 3. 看懂门槛和返回码

| 门槛 | 成功条件 | 0 的含义 |
| --- | --- | --- |
| `inventory` | 当前适用项执行完整，报告及必要子报告有效 | 记录建立成功；允许业务 fail 和 needs_review |
| `regression` | 输入可信且可比，对最新认可基线没有新退化 | 允许精确匹配、仍 open 的历史失败；不允许缺失执行或待裁定结果 |
| `release` | 同一实际候选的规则、模拟、live 报告均满足固定清单、来源核验和判分要求 | 仅本套件发布条件通过 |

返回码：`0` 当前门槛满足；`1` 质量不满足或待复核；`2` 缺少必需模式、配置或执行不完整；`3` 来源、散列、基线或比较口径无效。多种原因共存时按 `3 > 2 > 1 > 0` 取码，decision 保留原因。CLI 在尚未成功读取输入时可能只输出错误 JSON，不能把缺失 decision 当成通过。

`release` 的 `suite_release_status` 为 `passed` 或 `blocked`；其他门槛为 `not_evaluated`。`product_release_status` 始终为 `not_evaluated`。整个 P0 的场景扩展、业务指标、部署和试点验收仍须另行完成。

## 4. 首次业务审核与离线基线冻结

先由业务人员核对全部 22 条案例的客户表达、期望、严重度、适用模式、人工判分要求及修复任务，保留审核依据，再经专门规则审核更新案例的 `review_status` 和协议说明。不能批量改成 `reviewed` 来代替真实审核。已有草稿报告不会因此自动转正：标签和套件散列变化后，应提交规则并重新运行。

固定 CI 的 Python、uv、`uv.lock`、安装选项和运行环境，分别运行两种离线模式及 inventory。当前 workflow 使用 `ubuntu-latest`，宿主镜像仍可能滚动；必须核对记录的 `environment_hash`，有差异时先统一环境并重跑，不能把 Windows 本地报告直接当作 Linux 严格回归参照。

首次接纳允许已经明确登记的业务失败，但不允许执行错误、未执行或尚未裁定结果。每个旧缺陷在 `config/quality_known_issues.v1.json` 的 `issues` 中精确记录这些字段：

```json
{
  "issue_id": "实际修复任务编号",
  "status": "open",
  "mode": "mocked_model",
  "case_id": "来自报告的场景ID",
  "probe_id": "来自报告的探针",
  "checkpoint": "来自报告的检查点",
  "assertion_id": "来自报告的断言ID",
  "failure_type": "来自有效判定的失败类型",
  "severity": "critical",
  "resolved_commit": null
}
```

此处是字段模板，不是已经批准的缺陷。必须使用真实结果，不能豁免整个场景或把不同失败类型套进旧缺陷。`known_issue_id` 只是标签，原始失败不改为 pass。

将经审核、脱敏的完整运行文件复制到新目录，例如 `reports/quality/baselines/p0-01.v1/<acceptance_id>/run/`，保持文件字节不变，用 `load_run()` 再校验。`acceptance.json` 放在 `run/` 外面。源码的实际受测提交和之后保存审核材料的提交分别记录，不改写旧报告的 SHA。

### 4.1 `accept_baseline` 的审核输入

当前没有自动接纳 CLI 或远端审批服务。`accept_baseline()` 是可测试的 Python API：它校验输入并返回接纳单元，不修改 Git 分支或索引，也不能证明调用者伪造的字典可信。正式调用须使用从已接受目标分支加载的信任上下文。

先根据候选材料生成以下 **待审核 binding**，其键和值必须精确匹配。哈希使用 `quality_schema.content_hash()`，不要用普通格式化 JSON 的文件散列代替：

```python
binding = {
    "tested_commit": run["metadata"]["tested_commit"],
    "manifest_hash": run["manifest_hash"],
    "review_set_hash": content_hash(review_set),
    "previous_acceptance_id": None if previous is None else previous["acceptance_id"],
    "known_issues_hash": content_hash(issues),
}
```

空复核集合采用模块的 `EMPTY_REVIEW_SET`，即 `{"review_set_id":"empty","reviews":[]}`。非空集合必须先独立审核并将集合散列纳入 `accepted_review_set_hashes`；这一步不要求 release 或基线先通过。

审核人员核对源码、报告、判分、缺陷及前序版本后，在受保护的 `config/quality_trust.v1.json` 中登记 `approval_bindings[approval_ref] = binding`。`approval_ref` 指向真实审核记录；填一个字符串不会自动产生授权。正式调用示意如下，所有占位符都须替换成已审核材料：

```python
from pathlib import Path
from lead_cleaner.evaluation.quality_context import (
    git, load_trust_context, trusted_json,
)
from lead_cleaner.evaluation.quality_report import (
    EMPTY_REVIEW_SET, accept_baseline, load_run, write_record,
)
from lead_cleaner.evaluation.quality_schema import content_hash

root = Path.cwd()
trusted_ref = git(root, "rev-parse", "refs/remotes/origin/main")
trust = load_trust_context(root, trusted_ref)
issues = trusted_json(
    root, trusted_ref, "config/quality_known_issues.v1.json"
)["issues"]
acceptance_id = "本次新接纳ID"
run = load_run(root / "reports/quality/baselines/p0-01.v1" / acceptance_id / "run")
review_set = EMPTY_REVIEW_SET  # 有人工判分时换成受信任来源的完整固定集合
previous = None             # 仅首次初始化；之后须传最新认可记录
approval = {"approval_ref": "已登记的真实审核引用", "acceptance_id": acceptance_id}

record = accept_baseline(
    run, previous=previous, known_issues=issues,
    approval=approval, trust_context=trust, review_set=review_set,
)
write_record(
    root / "reports/quality/baselines/p0-01.v1" / acceptance_id / "acceptance.json",
    record,
)
```

首次初始化要求可信上下文显式含 `latest_accepted_baselines`，且当前 mode 尚无指针；初始化全部模式前它是 `{}`。后续接纳要求该 mode 指针等于 `previous.acceptance_id`，并重新运行 regression。前序被别人推进、缺少真实 approval binding、标签未审核、源码有改动或接纳 ID 已用过时，API 拒绝。

### 4.2 索引与缺陷共同接纳

分别为两个离线模式形成接纳记录。记录生成后还须在同一受审接纳变更中更新以下内容：

- `quality_baseline_index.v1.json` 的 `initial[mode]` 和 `accepted[mode]`：首次二者指向同一记录，以后 initial 不动，只推进 accepted。
- `quality_trust.v1.json` 的 `accepted_baselines[acceptance_id] = manifest_hash`，保留历史项；`latest_accepted_baselines[mode] = acceptance_id`。
- `quality_known_issues.v1.json` 使用接纳结果的缺陷快照。修为 pass 的对应缺陷同时转为 resolved，并记录实际 `resolved_commit`；不能先推进参照再补关缺陷。

索引单项的实际格式如下；对需要人工判分的基线保留其固定集合，否则 raw needs_review 会重新成为未裁定：

```json
{
  "acceptance_id": "已接纳的唯一ID",
  "directory": "reports/quality/baselines/p0-01.v1/已接纳的唯一ID/run",
  "manifest_hash": "实际manifest文件散列",
  "review_set": {"review_set_id": "empty", "reviews": []}
}
```

也可以使用 `review_set_path` 指向受保护的 `reports/quality/review-sets/<集合ID>.json`。CLI 从当前可信提交读取该集合。初始参照从 `initial[mode]` 读取，也支持 accepted 单项的 `initial_baseline`。后续 API 的 `previous` 须含最新 `acceptance_id`、经 `load_run()` 验证的 `run`、原固定 `review_set`，以及已经解析的 `initial_baseline`，保持累计比较链。

多个模式同时推进时，审核最终合并的缺陷快照，避免用另一个模式的旧快照覆盖已关闭缺陷。曾经在最近认可版本 pass 的断言再次失败，即使最初版本也失败、旧 issue 仍 open，回归仍阻断。

## 5. 日常回归与人工复核

先获取当前远端主分支，使用它的完整提交 SHA 作为 `--trusted-ref`。正式检查拒绝自行选择历史祖先快照。受测 SHA 则来自独立确定的候选提交，不能从待验报告反推。

```powershell
git fetch origin main
$trustedSha = (git rev-parse refs/remotes/origin/main).Trim()
$candidateSha = (git rev-parse HEAD).Trim()

uv run --no-sync python scripts/run_quality_eval.py check --gate regression --run '本次规则报告目录' --run '本次模拟报告目录' --candidate-sha $candidateSha --baseline-index config/quality_baseline_index.v1.json --trusted-ref $trustedSha --review-set empty
```

只有原始断言同时满足 `execution_status=completed`、`behavior_status=needs_review`、`manual_review=true`，才能通过人工复核裁定。自动 fail、执行错误和未调用不能人工改成 pass，即使 `manual_review=true` 也不例外。

复核集合是 `{ "review_set_id": "唯一ID", "reviews": [...] }`。每条记录包含 `review_id`、`run_manifest_hash`、六元 `key`、`output_hash`、`rubric_hash`、`verdict`、`reviewer`、`role`、`reason`、`reviewed_at`。`output_hash` 取断言的 `observation_hash`，绑定完整观察；rubric 使用原运行 metadata 中的 `rubric_hash`。`verdict` 可为 pass、fail、needs_review；fail 建议明确 `failure_type`，否则使用 `human_review_failure`。

自动判分项目不需要人工签字，原始自动失败也不能用人工意见覆盖。开放语义及首批事实、承诺争议采用开发和销售两方复核：协议及 CLI metadata 固定 `review_required_roles=["developer","sales"]`，每个必要角色必须由不同 `reviewer` 身份覆盖，且有效意见一致；缺少一方、同一人填写两个角色或存在分歧时仍为 needs_review。身份比较忽略首尾空格和大小写，但工具无法仅凭字符串确认真实身份；固定集合的 Git 审核必须确认实际人员、角色资格及签署记录，不能用不同化名冒充两人。角色要求须事先固定，不能修改已封存 metadata。

更正意见使用新 ID 和 `supersedes_review_id` 指向同一断言的旧记录，固定集合保留完整引用链。未裁定冲突仍为 needs_review，不取“最后一条意见”。集合通过真实 Git 审核、散列加入可信列表后，用 `--review-set <集合文件>` 重新 check，得到全新的 decision；不要修改原始报告或覆盖旧 blocked decision。这种检查不重新调用模型。

## 6. 规则升级的现有限制

案例、标签、严重度、断言器、知识资料、依赖、workflow、信任配置、基线索引和已知缺陷均属于受保护范围。它们改变后，普通 PR 的策略检查会阻断。首次标签审核、首基线接纳、后续指针推进也涉及这些文件，不能假设一次普通业务 PR 就会自动放行。

当前没有自动审核升级 API。应建立专门的规则升级或基线接纳 PR，附旧、新规则的差异、删项/放宽/豁免变化、对应对照报告及审核依据，由仓库管理员审核后按受控例外接纳，保留授权和实施记录；不能让普通 PR 用自己的评分器和 trust 文件重新自签为通过。远端保护及这套管理员正式接纳机制本次仍待完成。

评分口径变化需要按新口径重测比较对象，再建立新的参照链并保留旧链。当前 CLI 固定接受 `p0-01.v1`、22 场景及既定模式矩阵；新增协议版本还需要实现和审核相应支持，不能只改 JSON 的版本字符串。不可比报告不能用于宣称性能或质量提升。

## 7. 真实模型实验与本套件发布检查

真实实验使用 `.github/workflows/quality-live.yml` 的手动 `workflow_dispatch`。在 GitHub 配置 `quality-live` 环境及其 `QUALITY_MODEL_API_KEY` secret，审核费用与访问权限后，选择需要测试的提交所在 ref，明确填写 `model` 输入。不要把凭据放进参数、报告或仓库。

workflow 固定运行 live 的 10 场景，每例 3 trial，最多 60 次模型请求，不重试；模型名由显式输入传递。可用域名受协议白名单限制。未执行、超时和待人工判定都如实记录；模板兜底可用不代表模型成功。本次没有启动此 workflow 或调用真实 API。

若在受控环境直接运行，对应命令是：

```powershell
uv run --no-sync python scripts/run_quality_eval.py run --mode live --protocol config/quality_baseline.v1.json --model '经审核的实际模型标识' --allow-network --max-requests 60 --out 'data/runtime/quality-runs/新的live运行ID'
```

凭据从环境变量 `QUALITY_MODEL_API_KEY` 读取。仅有本地 live 报告仍不满足正式发布来源要求。

正式发布前，三个模式必须针对同一最终实际提交完成 CI 运行，且协议、评测器、套件、知识和依赖环境指纹一致。离线报告来自最终提交的 `push`，live 来自该提交的手动 `workflow_dispatch`。当前核验拒绝 `pull_request` 的 merge-ref 产物，不能把 PR 成功检查直接当作最终发布证据；提交变化后重跑所需模式。

workflow 先封存并上传报告 artifact，再通过 `scripts/write_quality_provenance.py` 生成独立外层索引，另行上传。不要把上传后的 artifact ID/digest 回填 manifest。下载报告及来源索引后，汇总为：

```json
{
  "reports": [
    {
      "directory": "下载并展开后的实际规则报告目录",
      "artifact_prefix": "rule_only",
      "provenance": {
        "repository": "jorlin1101-cyber/ai-sales-lead-crm-automation",
        "tested_commit": "实际受测完整SHA",
        "workflow_sha": "该次workflow实际提交SHA",
        "run_id": "真实GitHub运行ID",
        "attempt": "真实重试序号",
        "artifact_id": "真实artifact ID",
        "artifact_digest": "sha256:真实下载摘要",
        "manifest_hash": "实际manifest文件散列"
      }
    }
  ]
}
```

上例仅展示一项结构；发布索引须包含 rule_only、mocked_model、live 各一份。`directory` 可调整为本地解压位置，`artifact_prefix` 必须保持 archive 内真实目录前缀，其余来源字段取真实外层索引，不手填批准状态。不要再通过 `--run` 重复传入已在索引中的模式。

安装并登录有权读取该仓库 Actions 产物的 GitHub CLI 后运行：

```powershell
uv run --no-sync python scripts/run_quality_eval.py check --gate release --profile p0-01-ai-assisted.v1 --candidate-sha '最终候选完整SHA' --report-index 'data/runtime/quality-provenance/release-index.json' --baseline-index config/quality_baseline_index.v1.json --trusted-ref $trustedSha --review-set '已接纳的固定复核集合文件'
```

CLI 实际查询 GitHub API，核验仓库、事件、成功结束状态、候选提交、attempt、获准 workflow 内容、artifact 摘要及压缩包中的每个封存文件；之后 gate 再核验 manifest、来源和当前基线。报告内的 `trusted=true` 没有效力。artifact 过期或内容不匹配不能继续发布；当前 workflow 产物保留期为 30 天，应及时保存并审核需要长期保留的材料。

live 或复核尚未完成时 release 应保持 blocked。即使最终返回 0，也只表示本固定套件通过，不代替整体 P0 或线上业务验收。
