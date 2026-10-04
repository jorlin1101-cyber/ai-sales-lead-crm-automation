# S0 开发基线与同步验收报告

日期：2026-10-04。结论：S0 完成，A1—A10 全部通过。此报告记录本机实际执行结果，不把历史测试数字当作本次结果。

已完成原工作区保留与备份、GitHub 新副本建立、本地改动迁移、独立环境安装、工程质量与运行验收。后续开发使用新目录；原目录保留作回退。P0/P1 功能开发和真实模型准确度评测仍按[分版本实施方案](implementation-roadmap-2026-10-04.md)推进。

## 1 执行计划与实际完成情况

执行前列出的顺序为：保留原现场 → 建立 GitHub 新副本和功能分支 → 先测原版 → 逐项迁入本地改动 → 建立独立环境与数据库 → 验收并记录结果。实际按此执行；发现的 Windows 兼容问题另作最小修复并重新验证。

| 项目 | 已建立的基线 |
| --- | --- |
| 原工作区 | `D:\Python project\ai-sales-lead-crm-automation`，保留原状 |
| 原分支与 HEAD | `main` / `92d007f90d5adcd1ae904e14b2863228862e9f25` |
| 新开发目录 | `D:\Python project\ai-sales-lead-crm-automation-next` |
| 开发分支 | `codex/p0-quality-baseline` |
| GitHub 来源 | `https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation.git` |
| 克隆及收尾复核的远端 main | `04be2e5fbe672ce511eab36e6ab052795118b81b` |
| 最终运行代码基线 | `0e4f9e6b8750b3197e0df5740b1fca99c242da26`；之后的提交只整理本报告与文档入口 |
| 与远端的关系 | `origin/main` 是开发分支祖先；没有合并旧工作区的分叉历史 |
| 远端写入 | 未推送、未改 GitHub main、未发布或部署 |

选择新克隆是因为旧 main 与 GitHub main 历史已经分叉，同时旧工作区存在未提交修改。没有在旧目录强制拉取、重置或覆盖文件。

## 2 验收清单逐项核对

| 编号 | 执行前约定的验收项 | 本次证据与结果 |
| --- | --- | --- |
| A1 | 原版本、修改、配置和数据保持原状 | **通过**。原 HEAD、分支、状态不变，备份校验过程未改动原 index；210 个已跟踪文件、1 个未跟踪文件、5 个私密文件的 SHA-256 全部与备份清单一致。未操作原业务数据库。 |
| A2 | 未提交内容有备份，凭据不进入新仓库 | **通过**。Git bundle 校验成功；3 份补丁与原差异逐字节一致；1 个未跟踪副本和 5 个私密副本散列一致。在原 HEAD 的临时 index 上，组合补丁可应用。新仓仅跟踪 `.env.example`，不跟踪真实 `.env` 或数据库。 |
| A3 | 新副本来源、分支和远端版本明确 | **通过**。从记录的 GitHub main 完整克隆；创建指定 `codex/` 分支；收尾再次核对远端 SHA 未变化。 |
| A4 | 本地提示词与方案迁移，不覆盖新版能力 | **通过**。提示词基文件与远端完全一致后才迁入；迁入文件与旧本地修改的散列一致。实施方案按原文复制，文档入口合并保留新版链接。改动分别提交。 |
| A5 | 独立开发环境可安装、依赖一致 | **通过**。新建 `.venv`，Python 3.12.13；使用 `uv sync --frozen --extra dev` 按既有锁文件安装。52 个包依赖一致，未修改锁文件。 |
| A6 | 规范、格式、类型检查 | **通过**。Ruff 规范检查通过；179 个文件格式通过；Mypy 75 个源码文件通过。原版与迁移后的 Python 源码均验证。 |
| A7 | 离线测试、覆盖率、演示冒烟 | **通过**。最终交付配置下 699 passed / 2 skipped，覆盖率 95.21%，满足既有 95% 门槛。两项跳过是 PostgreSQL 专项，已由 A8 实跑补齐。7 个 CLI 场景、CLI 检索和离线 API 冒烟通过。 |
| A8 | PostgreSQL 迁移、并发和恢复 | **通过**。全新隔离 PostgreSQL 16.15 从空库迁移至 `0002_workflow_recovery (head)`；2 个专项测试通过，最终复核 2 passed / 0 skipped。 |
| A9 | 本机启动、网页、健康与 Docker | **通过**。本机首页、3 个实际静态资源、health、ready、线索处理均通过；Docker 最终构建、首页、health、容器内 ready、非 root 运行通过。Windows 换行问题已修复。 |
| A10 | 报告真实结果、边界和后续工作目录 | **通过**。本报告包含失败与修复、跳过原因、环境版本、日志位置、启动与回退方法；所有交付改动形成本地提交。本次临时应用进程与测试容器已清理。 |

这里的“全部通过”是上述 S0 工程验收通过，不代表 P0 功能已开发，也不代表模型回答准确率为 95.21%；该百分比是代码测试覆盖率。

## 3 备份、迁移与提交来源

原目录的本地备份位于：

`D:\Python project\ai-sales-lead-crm-automation\.git\codex-baselines\s0-20261004-141735`

内容包括 Git 历史 bundle、工作区/暂存区/组合补丁、未跟踪方案副本、私密配置与资料副本，以及散列清单。目录在 `.git` 内，不进入源码提交；私密内容没有输出到报告或复制到新副本。备份不是加密归档，应继续按原本的本机访问权限保管。

扫描原 `data` 目录没有发现 `.db/.sqlite/.sqlite3` 文件；原 `.env` 没有显式数据库连接或文件路径配置。因此本次没有可备份的已发现本地业务数据库，也没有连接外部业务数据库。此检查不覆盖其他启动环境中单独设置的数据库。

已验证 bundle 可读、文件副本一致、补丁可应用；没有做完整检出后的灾难恢复演练。日常回退直接使用保留的原工作区即可。

| 本地提交 | 内容 | 范围 |
| --- | --- | --- |
| `1a59b88` | 保留本地 recommendation prompt 换行调整 | 仅一个提示词文件；非空白内容、其它逻辑不变；实际提示词字符串的空白发生变化 |
| `9a1f6e8` | 迁入完整分版本方案与文档入口 | 未用旧文档索引覆盖新版索引 |
| `0e4f9e6` | `.gitattributes` 固定 shell 脚本 LF 换行 | 修复 Windows 检出后 Docker 无法启动的问题 |
| 本报告所在提交 | 新增验收报告、更新文档入口 | 仅文档 |

提示词文件 SHA-256：`5d791781549ce40abd4b6cfa0867999bdddc7a7c33513c789c3087f53ea7f647`。提示词版本常量仍是既有 `grounded-recommendation-v1`；基线通过提交与文件散列区分此次空白变更，不声称它改善了真实模型效果。

## 4 实测结果及发现的问题

### 4.1 测试与数据库

- GitHub 原版：699 passed / 2 skipped，95.21%，46.47 秒。
- 迁移后 Python 源码：699 passed / 2 skipped，95.21%，29.79 秒。
- 最终代码及已交付 `.env`：699 passed / 2 skipped，95.21%，29.49 秒。
- 独立 PostgreSQL 最终复核：2 passed，2.95 秒。这里不能把三次普通测试累加成更多独立用例。
- 普通测试与 PostgreSQL 测试使用独立进程、数据库配置和临时目录；普通测试保留 socket 隔离，PostgreSQL 仅放行本机连接。
- PostgreSQL 用例覆盖 4 个线程分配 8 个唯一轮次，以及模拟崩溃重试、人数更正、人工审核、旧版本审核 409 冲突与时间线。不是生产规模压测或所有故障类型证明。
- CLI 场景：high→qualified、medium→nurture、low→manual_review、invalid→校验失败、injection→manual_review、spam→spam、model-failure→timeout 回落；均符合预期。检索返回 3 个片段。
- 离线 API 冒烟返回 demo fixture / keyword_rrf / policy-v1、3 条资料来源；外部 socket 连接尝试为 0。

首次 PostgreSQL 测试结果是 1 passed / 1 error：Windows 系统临时目录拒绝访问，第二个测试尚未进入业务断言。改为新仓 `.git/codex-baselines/s0-20261004/` 下的专项临时目录后，两项通过；没有改业务代码、删测试或放宽断言。迁移先在空库执行，避免把测试自动建表误当作迁移成功。

### 4.2 本地启动与 Docker

本机服务只绑定 `127.0.0.1`，使用新建的 `data/runtime/s0-local-demo.sqlite3`。`/`、`/health`、`/ready`、`/assets/styles.css`、`/assets/app.js`、`/assets/workspace.js` 和 `POST /process-lead` 全部为 200，线索请求返回 3 条来源。首次手工探测误用了 `/static/` 前缀；随后按页面真实 `/assets/` 引用逐项验证，初始探测记录仍保留。

Docker 首轮构建成功，但启动脚本报 `set: Illegal option -`。原因是本机 `core.autocrlf=true` 把入口脚本检出为 CRLF；Git 中的原脚本是 LF。已增加 `*.sh text eol=lf` 并规范当前文件。重新检出验证和最终 Docker 重建均通过，未修改脚本业务逻辑。

最终 Docker 证据：

- 镜像：`leadflow-s0:20261004`。
- 本次镜像 ID：`sha256:d25225bafdc3c0f812a1b18a6a407eee30ae0365d5bdbd9c35e411f19a23aedc`。
- 宿主访问首页与 health：200；容器内 loopback 访问 ready：200、database=ready。
- `SERVICE_ACCESS_MODE=local` 下，Docker 桥接来的未认证 ready 请求是 401，符合现有访问策略。初次 smoke 把这一响应按 200 预期判错，已按访问来源重新核对，未放宽应用权限。
- 用户 UID 100，非 root；容器 Python 3.12.15。没有配置外部服务密钥。
- Docker ready 检查使用默认本地演示数据库；PostgreSQL 由前述独立专项验证，不混为同一测试。

此次下载并使用 `postgres:16`，实测版本为 PostgreSQL 16.15；Docker Engine 29.6.1。镜像基础标签仍沿用仓库配置，本次记录具体版本与镜像 ID，不承诺未来浮动标签构建出逐字节相同镜像。

测试用 PostgreSQL 容器使用独立名称、127.0.0.1:15432 和 tmpfs；验收后停止并删除，测试数据随之丢弃。应用测试容器及本机测试进程也已停止。最终应用镜像保留以便复查。为验收启动了 Docker Desktop，它启动时自动恢复了已有 Dify 容器；未对这些既有容器做单独修改或清理，Desktop 保持运行。

## 5 后续从哪里开始开发

请在 Codex 或编辑器中打开：

`D:\Python project\ai-sales-lead-crm-automation-next`

当前分支是 `codex/p0-quality-baseline`。旧目录继续保留；不要把两个目录各自新增的修改混在一起。后续 P0 开发沿用新目录和既有完整版本。

新副本已配置 `.venv` 和独立 `.env`。本地 `.env` 使用 demo、关闭外部网络、关闭模型和 Notion 写入、采用新 SQLite 演示文件，不需要原有密钥。它与 `.venv`、运行数据库都被 Git 忽略。

本机启动：

```powershell
Set-Location -LiteralPath 'D:\Python project\ai-sales-lead-crm-automation-next'
.\.venv\Scripts\python.exe -m uvicorn lead_cleaner.api.main:app --host 127.0.0.1 --port 18082
```

启动后打开 `http://127.0.0.1:18082`，停止时在该终端按 Ctrl+C。若端口被其他应用占用，换一个空闲端口。验收结束时没有留下正在运行的测试网页服务。

常规质量检查：

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/ci_offline_smoke.py
```

普通测试进程不要设置 PostgreSQL 专项的 `TEST_POSTGRES_URL`、`CONVERSATION_DATABASE_URL`、`CONVERSATION_AUTO_CREATE_SCHEMA` 覆盖值，否则会破坏用例的临时数据库隔离。需要重做 PostgreSQL 专项时，先建立全新测试数据库，再按 CI 流程执行 Alembic 迁移和两个专项测试；Windows 下另指定项目内 `--basetemp`，不能指向现有业务数据库或有用的文件目录。

此次依赖安装使用 `uv sync --frozen --extra dev --python <本机 Python 3.12.13 路径>`，没有升级锁文件。依赖损坏时按相同锁文件重建环境；不要先删除原目录或修改远端历史。

回退方法：停止新副本服务，重新打开原目录。原源码、配置和本地修改没有被更新版改写；新旧运行数据没有合并。后续若要同步业务数据或连接真实服务，需要作为独立变更核验，而不是直接替换连接串。

## 6 证据索引与未覆盖范围

完整本地日志位于新副本：`.git/codex-baselines/s0-20261004/`。它们不进入源码提交。

| 证据 | 文件 |
| --- | --- |
| 原目录与备份核对 | `original-preservation.log` |
| 最终依赖检查与环境指纹 | `dependencies-check.log`、`environment-manifest.json` |
| 静态检查 | `quality-ruff-final.log`、`quality-format-final.log`、`quality-mypy-final.log` |
| 原版、迁移后、交付配置全测 | `pytest-pristine.log`、`pytest-final.log`、`pytest-delivered-config.log` |
| 离线 API 与本机/CLI 验收 | `offline-smoke-final.log`、`local-smoke.json`、`cli-*.json` |
| PostgreSQL 迁移、版本与最终测试 | `postgres-migration.log`、`postgres-current-final.log`、`postgres-version.log`、`postgres-tests-final.log` |
| 首次环境失败与重试 | `postgres-tests.log`、`postgres-tests-retry.log`、`docker-smoke.log`、`docker-smoke-final.log` |
| 最终 Docker 构建与访问验收 | `docker-build-final.log`、`docker-smoke-final-local.log` |
| 新检出的 shell 换行校验 | `shell-eol-verification.log` |
| 临时 PostgreSQL 清理 | `postgres-cleanup.log` |

没有实测真实 OpenAI/DeepSeek/Qwen 调用、Notion 写入、外部渠道投递、线上 n8n 执行、真实模型准确率、生产压测或浏览器逐项交互操作。页面与静态文件通过 HTTP 验证。上述内容不属于这次 S0 完成声明，应在后续相应版本验收中单独覆盖。

S0 之后可进入方案中的 P0-01“冻结基线与失败案例”。当前工程基线已经建立；事实准确度、证据语义验证、撤回更正和业务评测等改进仍是待实施任务。
