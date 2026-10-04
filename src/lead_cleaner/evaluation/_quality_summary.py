"""Readable Chinese summaries, separate from immutable scoring and trust logic."""

import json
from collections import Counter
from typing import Any

_LABELS = {
    "rule_only": "规则与会话流程",
    "mocked_model": "模拟错误与合法对照",
    "live": "真实模型实验",
}
_STATUS = {
    "pass": "通过",
    "fail": "未满足要求",
    "needs_review": "待人工复核",
    "error": "执行错误",
    "not_run": "未执行",
}
_NAMES = {
    "M01": "合作需求撤回",
    "M02": "定制需求撤回",
    "M03": "本次客户身份更正",
    "F01": "英文人数与原话对应",
    "F02": "中文人数与原话对应",
    "G01": "无依据的预订确认",
    "G02": "无依据的供应保证",
}


def _text(value: Any, limit: int = 400) -> str:
    text = (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    )
    return text.replace("|", "／").replace("\n", " ")[:limit]


def trial_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len({row["mode"] for row in rows}) > 1:
        raise ValueError("trial summary must not mix execution modes")
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["case_id"], row["trial_id"]), []).append(row)
    counts: dict[str, dict[str, int]] = {}
    for (case, _), group in groups.items():
        required = [row for row in group if row.get("mandatory", True)]
        stages = [row for row in required if row["assertion_id"].endswith("_executed")]
        business = [row for row in required if row not in stages]

        def passed(values: list[dict[str, Any]]) -> bool:
            return bool(values) and all(
                row["execution_status"] == "completed" and row["behavior_status"] == "pass"
                for row in values
            )

        totals = counts.setdefault(
            case,
            {
                "planned": 0,
                "completed": 0,
                "business_pass": 0,
                "model_pass": 0,
                "whole_case_pass": 0,
            },
        )
        totals["planned"] += 1
        totals["completed"] += int(all(row["execution_status"] == "completed" for row in required))
        totals["business_pass"] += int(passed(business))
        totals["model_pass"] += int(
            all(row["mode"] == "live" for row in group) and passed(stages) and passed(business)
        )
        totals["whole_case_pass"] += int(passed(required))
    return counts


def render_run_summary(run: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    metadata, rows = run["metadata"], run["assertions"]
    mode = metadata["mode"]
    counts = Counter(row["behavior_status"] or row["execution_status"] for row in rows)
    case_index = {case["case_id"]: case for case in cases}
    lines = [
        "# 销售助手质量检查报告",
        "",
        f"检查版本：`{metadata['tested_commit']}`。模式：{_LABELS[mode]}。",
        f"适用业务场景：{metadata['scenario_count']} 个；检查点记录：{len(rows)} 条。",
        f"通过 {counts['pass']}；未满足要求 {counts['fail']}；待复核 {counts['needs_review']}；执行错误 {counts['error']}；未执行 {counts['not_run']}。",
        "",
        "报告状态：临时工程报告，尚未成为正式业务基线。"
        if metadata.get("provisional")
        else "报告状态：代码与标注满足正式运行条件；基线接纳和发布仍须单独检查。",
        f"真实模型请求：{metadata.get('real_model_calls', 0)} 次。"
        + (
            "真实 AI 质量未测。"
            if mode != "live" or metadata.get("live_simulated")
            else "本报告只说明本批输入与配置的表现，开放语义仍需人工复核。"
        ),
        "本次报告生成成功不等于产品可发布；整体 P0 发布未评估。",
        "",
        "## 当前问题及下一步",
        "",
        "| 场景 | 客户表达 | 当前结果 | 正确要求 | 检查位置 | 下一步 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        if row["behavior_status"] == "pass":
            continue
        case = case_index[row["case_id"]]
        payload = case["payload"]
        message = payload.get(
            "message",
            payload.get(
                "customer_message", payload.get("turns", payload.get("api_turns", "见固定案例原文"))
            ),
        )
        task = (
            "P0-03 人数与原话核验"
            if row["case_id"].startswith("F")
            else (
                "P0-05 承诺与证据核验" if row["case_id"].startswith("G") else "P0-04 当前需求更正"
            )
        )
        status = row["behavior_status"] or row["execution_status"]
        if status in {"error", "not_run"}:
            task = "先排除执行问题，再重新评测"
        elif status == "needs_review":
            task = "按业务标准进行人工复核"
        label = _NAMES.get(row["case_id"], row["case_id"])
        lines.append(
            f"| {row['case_id']} {_text(label)} | {_text(message)} | {_STATUS.get(status, status)}：{_text(row['actual'])} | {_text(row['expected'])} | {row['probe_id']} / {row['checkpoint']} | {task} |"
        )
    if all(row["behavior_status"] == "pass" for row in rows):
        lines.append("| 本批检查未发现不满足项 | — | 仅限当前案例 | — | — | 继续检查未覆盖范围 |")
    lines.extend(
        [
            "",
            "## 版本变化",
            "",
            "原始报告保持封存。相对初始版本和最近认可版本的差异由独立 regression 判断生成；尚未选择已接受基线时，不能声称质量提升。",
        ]
    )
    if mode == "live":
        lines.extend(
            [
                "",
                "## 重复试验",
                "",
                "| 场景 | 已完成 | 业务结果通过 | 目标模型通过 | 整例通过 |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for case_id, totals in trial_summary(rows).items():
            n = totals["planned"]
            lines.append(
                f"| {case_id} | {totals['completed']}/{n} | {totals['business_pass']}/{n} | {totals['model_pass']}/{n} | {totals['whole_case_pass']}/{n} |"
            )
    if mode == "rule_only":
        lines.extend(
            [
                "",
                "既有检索：18 条查询、3 条查询路径，见 retrieval-v4.json。推荐：12 条数据契约，见 recommendation-contract.json；两者不与业务场景加总成准确率。",
            ]
        )
    lines.extend(["", "已知业务失败继续记失败。模拟错误不用于估计真实模型出错概率。", ""])
    return "\n".join(lines)
