"""Customer-facing summaries must keep execution, business, and AI claims separate."""

import pytest

from lead_cleaner.evaluation._quality_summary import _text, render_run_summary, trial_summary


def row(
    case="F01",
    trial="1",
    assertion="business",
    *,
    mode="live",
    behavior="pass",
    execution="completed",
    mandatory=True,
):
    return {
        "mode": mode,
        "case_id": case,
        "trial_id": trial,
        "assertion_id": assertion,
        "probe_id": "main",
        "checkpoint": "final",
        "execution_status": execution,
        "behavior_status": behavior if execution == "completed" else None,
        "mandatory": mandatory,
        "actual": {"人数": 8},
        "expected": {"人数": 6},
    }


def test_live_trials_distinguish_fallback_business_from_model_success():
    rows = [
        row(trial="1"),
        row(trial="1", assertion="understanding_executed"),
        row(trial="1", assertion="generation_executed"),
        row(trial="2"),
        row(trial="2", assertion="understanding_executed"),
        row(trial="2", assertion="generation_executed", execution="error"),
        row(trial="3", behavior="needs_review"),
        row(trial="3", assertion="understanding_executed"),
        row(trial="3", assertion="generation_executed"),
    ]
    assert trial_summary(rows) == {
        "F01": {
            "planned": 3,
            "completed": 2,
            "business_pass": 2,
            "model_pass": 1,
            "whole_case_pass": 1,
        }
    }
    # Returning a fallback answer cannot turn an unexecuted model stage into success.
    rows[5]["execution_status"] = "not_run"
    assert trial_summary(rows)["F01"]["model_pass"] == 1


def test_model_stage_completion_does_not_prove_quality_and_optional_checks_do_not_inflate_trials():
    rows = [
        row("F01", behavior="fail"),
        row("F01", assertion="generation_executed"),
        row("G01"),
        row("G01", assertion="generation_executed", behavior="fail"),
        row("M01"),
        row("M01", assertion="generation_executed"),
        row("M01", assertion="diagnostic", execution="error", mandatory=False),
        row("no-model"),
    ]
    summary = trial_summary(rows)
    assert summary["F01"] == {
        "planned": 1,
        "completed": 1,
        "business_pass": 0,
        "model_pass": 0,
        "whole_case_pass": 0,
    }
    assert summary["G01"] == {
        "planned": 1,
        "completed": 1,
        "business_pass": 1,
        "model_pass": 0,
        "whole_case_pass": 0,
    }
    assert summary["M01"] == {
        "planned": 1,
        "completed": 1,
        "business_pass": 1,
        "model_pass": 1,
        "whole_case_pass": 1,
    }
    assert summary["no-model"]["model_pass"] == 0
    assert trial_summary([]) == {}


@pytest.mark.parametrize("mode", ["rule_only", "mocked_model"])
def test_offline_execution_does_not_produce_real_model_success_counts(mode):
    summary = trial_summary([row(mode=mode), row(mode=mode, assertion="generation_executed")])
    assert summary["F01"]["business_pass"] == 1
    assert summary["F01"]["whole_case_pass"] == 1
    assert summary["F01"]["model_pass"] == 0


def metadata(mode="live", **changes):
    result = {
        "mode": mode,
        "tested_commit": "a" * 40,
        "scenario_count": 5,
        "provisional": True,
        "real_model_calls": 5,
    }
    result.update(changes)
    return result


def test_chinese_summary_explains_failure_review_and_execution_next_steps():
    rows = [
        row("F01", behavior="fail"),
        row("G01", behavior="fail"),
        row("M01", behavior="fail"),
        row("F02", execution="not_run"),
        row("unknown", execution="error"),
        row("review", behavior="needs_review"),
    ]
    cases = [
        {"case_id": "F01", "payload": {"message": "人数六人|不是八人\n请确认。"}},
        {"case_id": "G01", "payload": {"customer_message": "请先查询供应。"}},
        {"case_id": "M01", "payload": {"turns": ["先定制", "暂不定制"]}},
        {"case_id": "F02", "payload": {"api_turns": ["两位成人"]}},
        {"case_id": "unknown", "payload": {}},
        {"case_id": "review", "payload": {"message": "这算作已经保证了吗？"}},
    ]
    text = render_run_summary({"metadata": metadata(), "assertions": rows}, cases)
    assert "通过 0；未满足要求 3；待复核 1；执行错误 1；未执行 1" in text
    assert "临时工程报告" in text
    assert "人数六人／不是八人 请确认。" in text
    assert "P0-03 人数与原话核验" in text
    assert "P0-05 承诺与证据核验" in text
    assert "P0-04 当前需求更正" in text
    assert "先排除执行问题，再重新评测" in text
    assert "按业务标准进行人工复核" in text
    assert "见固定案例原文" in text
    assert "真实模型请求：5 次" in text
    assert "本报告只说明本批输入与配置的表现" in text
    assert "整体 P0 发布未评估" in text
    assert "不能声称质量提升" in text
    assert "已知业务失败继续记失败" in text
    assert "| 场景 | 已完成 | 业务结果通过 | 目标模型通过 | 整例通过 |" in text
    assert "| review | 1/1 | 0/1 | 0/1 | 0/1 |" in text
    assert "| F02 | 0/1 | 0/1 | 0/1 | 0/1 |" in text


@pytest.mark.parametrize("mode", ["rule_only", "mocked_model", "live"])
def test_all_pass_summary_does_not_overclaim_release_or_combine_datasets(mode):
    run = {"metadata": metadata(mode, provisional=False), "assertions": [row(mode=mode)]}
    text = render_run_summary(run, [{"case_id": "F01", "payload": {}}])
    assert "本批检查未发现不满足项" in text
    assert "基线接纳和发布仍须单独检查" in text
    assert "当前案例" in text
    assert "产品可发布；整体 P0 发布未评估" in text
    assert ("## 重复试验" in text) is (mode == "live")
    if mode == "rule_only":
        assert "18 条查询、3 条查询路径" in text
        assert "12 条数据契约" in text
        assert "不与业务场景加总成准确率" in text
    if mode != "live":
        assert "真实 AI 质量未测" in text
        assert "模拟错误不用于估计真实模型出错概率" in text


def test_simulated_live_summary_explicitly_marks_real_quality_unmeasured():
    run = {"metadata": metadata(live_simulated=True), "assertions": [row()]}
    run["metadata"].pop("real_model_calls")
    text = render_run_summary(run, [{"case_id": "F01", "payload": {}}])
    assert "真实模型请求：0 次。真实 AI 质量未测" in text


def test_table_cells_escape_separators_and_bound_visible_length():
    assert _text("甲|乙\n丙") == "甲／乙 丙"
    assert _text({"客户": "甲|乙"}) == '{"客户": "甲／乙"}'
    assert _text("很长的客户原始输入", limit=4) == "很长的客"


def test_mixed_modes_cannot_be_grouped_into_one_trial_denominator():
    with pytest.raises(ValueError, match="mode"):
        trial_summary([row(mode="live"), row(mode="mocked_model")])
