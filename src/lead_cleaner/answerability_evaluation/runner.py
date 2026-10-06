"""Compose real observations, independent grading and immutable artifacts."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from lead_cleaner.answerability_evaluation.adapters import run_observations
from lead_cleaner.answerability_evaluation.checks import evaluate_assertions
from lead_cleaner.answerability_evaluation.context import build_metadata, load_protocol
from lead_cleaner.answerability_evaluation.dataset import load_dataset
from lead_cleaner.answerability_evaluation.metrics import (
    aggregate_metrics,
    score_retrieval,
)
from lead_cleaner.answerability_evaluation.reports import seal_run, stage_observations
from lead_cleaner.answerability_evaluation.retrieval import run_retrieval


def render_summary(
    metadata: dict[str, Any],
    assertions: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    retrieval: list[dict[str, Any]],
    metrics: dict[str, Any],
    dataset: dict[str, Any] | None = None,
) -> str:
    states = Counter(a["behavior_status"] or a["execution_status"] for a in assertions)

    def display(metric: dict[str, Any]) -> str:
        value = metric["value"]
        if value is not None:
            return f"{metric['numerator']}/{metric['denominator']}（{value:.1%}）"
        if metric["applicability"] == "not_applicable":
            return "不适用（N/A）"
        return f"待裁定：已确认 {metric['numerator']} / 计划 {metric['denominator']}；待复核 {metric.get('needs_review_count', 0)}"

    lines = [
        "# P0-02 答案可得性评测",
        "",
        f"模式：{metadata['mode']}；协议：{metadata['protocol_id']}。",
        f"受测提交：{metadata['tested_commit']}；本地源码有修改：{metadata['source_dirty']}。",
        f"业务标签已确认：{metadata['business_labels_reviewed']}；报告为草案：{metadata['provisional']}。",
        "",
        f"场景 24 个；本模式观察 {len(observations)} 轮；独立检索 {len(retrieval)} 单元。",
        f"检查项统计：通过 {states['pass']}、未通过 {states['fail']}、待复核 {states['needs_review']}、执行错误 {states['error']}、未执行 {states['not_run']}。真实模型调用 0 次；真实客户质量未评估。",
        "",
    ]
    grouped = metrics.get("groups", {"legacy": metrics})
    labels = {
        "handbook": "原手册业务组",
        "synthetic_special": "合成边界专项",
        "legacy": "旧版固定队列",
    }
    if "groups" in metrics:
        lines.extend(
            [
                "原手册业务组与合成边界专项分别统计；不计算混合产品准确率。",
                "两组问题均为合成问题；原手册组的知识来源为原始 8 页面、47 片段，专项知识为合成夹具。",
                "",
            ]
        )
    for group, group_metrics in grouped.items():
        counts = group_metrics.get("counts")
        lines.extend([f"## {labels[group]}", ""])
        if counts:
            lines.append(
                f"计划 {counts['case_count']} 场景 / {counts['turn_count']} 轮 / {counts['retrieval_units']} 独立检索单元；实际记录 {counts['observed_turn_count']} 轮 / {counts['observed_retrieval_units']} 检索单元。"
            )
            lines.append("")
        lines.extend(["| 检查 | 成功数 / 固定计划分母 |", "| --- | --- |"])
        for state, label in (
            ("all", "全部轮次"),
            ("state:answerable", "完整回答"),
            ("state:partial", "部分回答"),
            ("state:unanswerable", "无答案安全处理"),
        ):
            metric = group_metrics["replies"].get(state)
            if metric is not None:
                lines.append(f"| {label} | {display(metric)} |")
        lines.extend(
            [
                "",
                "### 检索检查",
                "",
                "| 路径 | 支持命中 | 可答要点召回 | nDCG |",
                "| --- | --- | --- | --- |",
            ]
        )
        for path, values in group_metrics["retrieval"].items():
            lines.append(
                f"| {path} | {display(values['supported_facet_hit'])} | {display(values['answerable_facet_recall'])} | {display(values['ndcg'])} |"
            )
    if not retrieval:
        lines.append("本模式不重复执行独立检索基准；实际回复上下文仍逐轮记录。")
    lines.extend(
        [
            "",
            "## 回复依据观察",
            "",
            "| 场景 / 轮次 | 实际检索片段数 | 回复实际采用的片段数 | 有依据可答要点数 |",
            "| --- | --- | --- | --- |",
        ]
    )
    content_rows = {
        (row["case_id"], row["turn_id"]): row
        for row in assertions
        if row["assertion_id"] == "answer_content"
    }
    for observation in observations:
        row = content_rows[(observation["case_id"], observation["turn_id"])]
        covered = len(row.get("details", {}).get("context_supported_facets", []))
        lines.append(
            f"| {observation['case_id']} / {observation['turn_id']} | {len(observation.get('retrieved_chunks', []))} | {len(observation.get('provided_context', []))} | {covered} |"
        )
    lines.extend(
        [
            "",
            "未完成语义复核时，上表是已确认成功的数量，不能当最终业务准确率。",
            "知识缺口由完整快照标签确定；检索遗漏由实际检索与支持组合确定；无依据作答和过度拒答需完整声明复核。",
            "没有生产分类器，因此不显示虚构的三态预测准确率。规则模式没有模型调用属于正常情况。",
            "mocked_model 仅检验受控链路，不代表真实模型能力。",
            "原 P0-01 基线和 11 项已知缺陷另行保留。本报告不能批准产品发布。",
            "",
            "## 需要处理的断言",
            "",
        ]
    )
    for row in assertions:
        if row["behavior_status"] != "pass":
            lines.append(
                f"- {row['case_id']}/{row['turn_id']}/{row['assertion_id']}：{row['behavior_status'] or row['execution_status']}；{row['failure_type'] or '需真实语义复核'}"
            )
    if dataset is not None and metadata["protocol_id"] == "p0-02.v2":
        lines.extend(_render_turn_details(dataset, observations, assertions))
    return "\n".join(lines) + "\n"


def _render_turn_details(
    dataset: dict[str, Any],
    observations: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
) -> list[str]:
    """Human-readable evidence; all gold labels are used after API execution only."""
    observed = {(o["case_id"], o["turn_id"]): o for o in observations}
    lines = [
        "",
        "## 逐轮实际输出与复核依据",
        "",
        "应答要点是评分标签，未作为系统输入。以下原文不代表标签已经业务审核。",
        "",
    ]
    group_labels = {"handbook": "原手册业务组", "synthetic_special": "合成边界专项"}
    for case in dataset["cases"]:
        snapshot = dataset["snapshots"][case["snapshot_id"]]
        chunks = {item["chunk"]["chunk_id"]: item["chunk"] for item in snapshot["chunks"]}
        for turn in case["turns"]:
            key = (case["case_id"], turn["turn_id"])
            obs = observed.get(key, {})
            current = [a for a in assertions if (a["case_id"], a["turn_id"]) == key]
            status = (
                "；".join(
                    f"{a['assertion_id']}={a['behavior_status'] or a['execution_status']}"
                    for a in current
                )
                or "未执行"
            )
            lines.extend(
                [
                    f"### {case['case_id']} / {turn['turn_id']} · {group_labels[case['evaluation_group']]}",
                    "",
                    f"知识来源：{case['corpus_origin']}；问题来源：{case['scenario_origin']}；标签审核：{case['review_status']}。",
                    f"执行：{obs.get('execution_status', 'not_run')}；API 状态：{obs.get('api_status')}；语义复核：{status}。",
                    "",
                    "客户提问（实际输入原文）：",
                    "",
                    *["> " + line for line in turn["message"].splitlines()],
                    "",
                    "中文阅读译文（不送入系统）：",
                    "",
                    *["> " + line for line in turn["message_zh"].splitlines()],
                    "",
                    "实际回复：",
                    "",
                    *[
                        "> " + line
                        for line in (obs.get("reply_text") or "（没有生成回复）").splitlines()
                    ],
                    "",
                    "评分应答要点：",
                    "",
                ]
            )
            for facet in turn["facets"]:
                lines.append(
                    f"- {facet['facet_id']}：{facet['description']}；是否必需：{facet['required']}；完整快照是否支持：{facet['answerable']}。"
                )
            context = obs.get("provided_context", [])
            lines.extend(["", "实际送入回复环节的资料：", ""])
            if not context:
                lines.append("- 无资料片段。")
            for item in context:
                chunk_id = item["chunk_id"]
                chunk = chunks.get(chunk_id, {})
                lines.append(
                    f"- {chunk_id}：{chunk.get('source_title') or '无标题'}；来源 {chunk.get('source_path') or chunk.get('notion_page_id') or case['snapshot_id']}。"
                )
            lines.append("")
    return lines


def run_suite(root: Path, mode: str, output: Path, protocol_id: str = "p0-02.v1") -> dict[str, Any]:
    if output.exists():
        raise ValueError("Output already exists; sealed evidence cannot be overwritten")
    dataset, protocol = load_dataset(root, protocol_id), load_protocol(root, protocol_id)
    before = build_metadata(root, dataset, mode, protocol)
    work = output.with_name(output.name + ".work")
    if work.exists():
        raise ValueError("Execution workspace already exists")
    observations = run_observations(root, dataset, mode, work)
    stage_observations(output, observations)
    retrieval = run_retrieval(dataset) if mode == "rule_only" else []
    turns = {(c["case_id"], t["turn_id"]): t for c in dataset["cases"] for t in c["turns"]}
    for row in retrieval:
        row["metrics"] = score_retrieval(
            turns[(row["case_id"], row["turn_id"])],
            row["results"],
            k=protocol["top_k"],
            execution_status=row["execution_status"],
        )
    assertions = evaluate_assertions(dataset, observations)
    after = build_metadata(root, dataset, mode, protocol)
    fingerprint_names = [
        "protocol_hash",
        "dataset_hash",
        "knowledge_hash",
        "evaluator_hash",
        "code_hash",
        "environment_hash",
    ]
    if protocol_id == "p0-02.v2":
        fingerprint_names.extend(["source_manifest_hash", "group_source_hash"])
    for name in fingerprint_names:
        if before[name] != after[name]:
            raise ValueError("Inputs changed during execution: " + name)
    metrics = aggregate_metrics(dataset, observations, assertions, retrieval, mode)
    return seal_run(
        output,
        {
            "metadata": after,
            "observations": observations,
            "assertions": assertions,
            "retrieval": retrieval,
            "metrics": metrics,
            "summary": render_summary(after, assertions, observations, retrieval, metrics, dataset),
        },
        expected_keys=before["expected_keys"],
        expected_retrieval_keys=before["expected_retrieval_keys"],
    )
