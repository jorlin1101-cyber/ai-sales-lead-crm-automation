# Contributing

感谢你愿意改进这个项目。提交改动前，请先阅读下面的最小协作约定。

## 开发环境

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

项目要求 Python 3.12 或更高版本；CI 使用 Python 3.12。

## 建议流程

1. 从最新的 `main` 创建功能分支。
2. 每次提交只解决一个清晰的问题。
3. 同步补充或更新测试。
4. 不要提交 `.env`、API Key、真实客户数据或私有知识库快照。
5. 提交 Pull Request 前运行完整质量门禁。

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest -q
python scripts/ci_offline_smoke.py
```

## 测试与网络安全

- 自动测试默认禁止外部 socket。
- 测试不得依赖 OpenAI、DeepSeek、Notion 或 embedding 服务。
- 外部服务应通过 fake、stub 或依赖注入替代。
- 新增 fallback 时，必须同时测试 fallback 原因和安全输出。

## 文档约定

- README 只保留项目入口和关键证据。
- 当前契约放在 `docs/`。
- 已废弃的设计不进入当前文档索引；必要背景通过 ADR 记录。
- 修改公共字段时，同步更新 Schema、测试和 `docs/api-contract.md`。

## 提交信息

建议使用简短、可读的提交类型：

```text
feat: add ...
fix: handle ...
test: cover ...
docs: update ...
refactor: simplify ...
```

## Pull Request

PR 描述至少说明：

- 改了什么；
- 为什么需要；
- 如何验证；
- 是否改变 API、评分规则、RAG 或 n8n 契约；
- 是否存在迁移或兼容性影响。
