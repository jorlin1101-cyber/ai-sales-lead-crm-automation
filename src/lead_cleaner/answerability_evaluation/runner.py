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
    score_retrieval,
    summarize_replies,
    summarize_retrieval,
)
from lead_cleaner.answerability_evaluation.reports import seal_run, stage_observations
from lead_cleaner.answerability_evaluation.retrieval import run_retrieval


def render_summary(
    metadata: dict[str, Any],
    assertions: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    retrieval: list[dict[str, Any]],
    metrics: dict[str, Any],
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
        f"模式：{metadata['mode']}；协议：p0-02.v1。",
        f"受测提交：{metadata['tested_commit']}；本地源码有修改：{metadata['source_dirty']}。",
        f"业务标签已确认：{metadata['business_labels_reviewed']}；报告为草案：{metadata['provisional']}。",
        "",
        f"场景 24 个；本模式观察 {len(observations)} 轮；独立检索 {len(retrieval)} 单元。",
        f"检查项统计：通过 {states['pass']}、未通过 {states['fail']}、待复核 {states['needs_review']}、执行错误 {states['error']}、未执行 {states['not_run']}。真实模型调用 0 次；真实客户质量未评估。",
        "",
        "| 检查 | 成功数 / 固定计划分母 |",
        "| --- | --- |",
    ]
    for state, label in (
        ("answerable", "完整回答"),
        ("partial", "部分回答"),
        ("unanswerable", "无答案安全处理"),
    ):
        lines.append(f"| {label} | {display(metrics['replies']['state:' + state])} |")
    lines.extend(
        [
            "",
            "## 检索检查",
            "",
            "| 路径 | 支持命中 | 可答要点召回 | nDCG |",
            "| --- | --- | --- | --- |",
        ]
    )
    for path, values in metrics["retrieval"].items():
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
    return "\n".join(lines) + "\n"


def run_suite(root: Path, mode: str, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError("Output already exists; sealed evidence cannot be overwritten")
    dataset, protocol = load_dataset(root), load_protocol(root)
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
    for name in (
        "protocol_hash",
        "dataset_hash",
        "knowledge_hash",
        "evaluator_hash",
        "code_hash",
        "environment_hash",
    ):
        if before[name] != after[name]:
            raise ValueError("Inputs changed during execution: " + name)
    metrics = {
        "replies": summarize_replies(dataset, observations, assertions),
        "retrieval": summarize_retrieval(retrieval),
        "retrieval_applicability": "applicable" if mode == "rule_only" else "not_applicable",
    }
    return seal_run(
        output,
        {
            "metadata": after,
            "observations": observations,
            "assertions": assertions,
            "retrieval": retrieval,
            "metrics": metrics,
            "summary": render_summary(after, assertions, observations, retrieval, metrics),
        },
        expected_keys=before["expected_keys"],
        expected_retrieval_keys=before["expected_retrieval_keys"],
    )
