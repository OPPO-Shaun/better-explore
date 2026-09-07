"""端到端示例：用一个模拟 agent workflow 演示五个阶段全流程。

运行::

    python examples/demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_eval import (
    AssetLedger,
    DeterministicEvaluator,
    EvalRunner,
    Gate,
    GateConfig,
    GoldenCase,
    Intervention,
    LearningLedger,
    LLMJudge,
    TaskEpisode,
    Tracer,
    TrajectoryEvaluator,
    VersionTags,
    load_golden_set,
    outcome_metrics,
    step_metrics,
    system_metrics,
    trajectory_metrics,
)
from agent_eval.episode import AcceptanceCriterion

ROOT = Path(__file__).resolve().parent.parent
TAGS = VersionTags(
    prompt_version="p-v3",
    model_version="demo-llm-2026-01",
    tool_defs_version="tools-v2",
    workflow_version="wf-v5",
)


# --------------------------------------------------------- 模拟的 agent workflow

def run_demo_workflow(case: GoldenCase) -> TaskEpisode:
    """一个模拟 workflow：阶段1 埋点 tracing，阶段2 产出 Task Episode。"""
    tracer = Tracer(task_id=case.case_id, version_tags=TAGS)

    with tracer.span("plan", kind="node", inputs=case.goal) as sp:
        sp.outputs = f"plan for: {case.goal}"

    output: str
    if case.task_type == "qa":
        expr = case.inputs["question"].split("=")[0].strip()
        result = eval(expr, {"__builtins__": {}})  # 演示用途的固定算式
        tracer.record_tool_call("calculator", args={"expr": expr}, result=result)
        tracer.record_llm_call("demo-llm", prompt=case.goal,
                               completion=str(result),
                               input_tokens=50, output_tokens=8,
                               cost_usd=0.0004, duration_ms=120)
        output = f"答案是 {int(result) if float(result).is_integer() else result}"
    elif case.inputs.get("query"):
        tracer.record_tool_call("search", args={"q": case.inputs["query"]},
                                result=["https://www.python.org"])
        tracer.record_tool_call("summarize",
                                args={"docs": 1}, result="python.org 是官网")
        tracer.record_llm_call("demo-llm", prompt=case.goal,
                               completion="https://www.python.org",
                               input_tokens=120, output_tokens=15,
                               cost_usd=0.001, duration_ms=200)
        output = "官网是 https://www.python.org"
    else:
        output = "请输入查询内容"

    trace = tracer.finish()
    episode = TaskEpisode(
        episode_id=case.case_id,
        goal=case.goal,
        task_type=case.task_type,
        acceptance=[
            AcceptanceCriterion(
                criterion_id=c["criterion_id"],
                description=c.get("description", ""),
                kind=c.get("kind", "exact_match"),
                expected=c.get("expected"),
            )
            for c in case.acceptance
        ],
        reference_trajectory=case.reference_trajectory,
        final_output=output,
    )
    episode.add_trace(trace)
    return episode


def demo_judge(case: GoldenCase, episode: TaskEpisode) -> tuple[float, str]:
    """演示用 judge（真实场景应封装 DeepEval / EvalScope / 模型 API）。"""
    ok = episode.succeeded
    return (0.95 if ok else 0.3,
            "输出满足验收标准" if ok else "输出未满足验收标准")


def main() -> None:
    print("=" * 60)
    print("阶段4: 加载评测集并运行评测器")
    cases = load_golden_set(ROOT / "datasets/golden/example.jsonl")
    runner = EvalRunner([
        DeterministicEvaluator(),
        TrajectoryEvaluator(mode="superset"),
        LLMJudge(demo_judge),
    ])
    report = runner.run(cases, run_demo_workflow)
    episodes = report["episodes"]
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))

    print("=" * 60)
    print("阶段3: 分层指标")
    print("结果层:", json.dumps(outcome_metrics(episodes), ensure_ascii=False))
    print("系统层:", json.dumps(system_metrics(episodes), ensure_ascii=False))
    ep = episodes[0]
    print("轨迹层(示例):",
          json.dumps(trajectory_metrics(ep), ensure_ascii=False))
    print("步骤层(示例):",
          json.dumps(step_metrics(ep, expected_tools=cases[0].expected_tools),
                     ensure_ascii=False))

    print("=" * 60)
    print("阶段3: 资产层（四级证据封顶）")
    assets = AssetLedger()
    assets.register("calculator", kind="tool")
    assets.register("search", kind="tool")
    assets.register("summarize", kind="tool")
    assets.register("unused-skill", kind="skill")  # 配置了但从未使用 → Present 封顶 74
    for e in episodes:
        if e.trace:
            assets.observe_trace(e.trace)
    print(json.dumps(assets.summary(), ensure_ascii=False, indent=2))

    print("=" * 60)
    print("阶段5: CI 门禁")
    gate = Gate(GateConfig(min_task_success_rate=0.75,
                           min_criteria_pass_rate=0.75,
                           max_avg_cost_usd=0.01),
                baseline_path="/tmp/agent-eval-baseline.json")
    gate_report = gate.check(episodes, TAGS)
    print(gate_report.to_json(indent=2))
    if gate_report.passed:
        gate.save_baseline(gate_report)
        print("门禁通过，已保存为新基线")

    print("=" * 60)
    print("阶段5: Learning Capture 飞轮（修复—验证分离）")
    ledger = LearningLedger(asset_ledger=assets)
    iv = ledger.propose(Intervention(
        intervention_id="iv-001",
        description="为 search 工具增加空查询兜底提示",
        target_asset_id="search",
        failure_pattern="search 类任务空查询崩溃",
    ))
    ledger.apply("iv-001", baseline_episodes=episodes)
    print("applied（此时不涨分）:", iv.status)
    # 用"后续窗口"重跑验证——只有此刻资产才能升 Outcome-supported
    later = [run_demo_workflow(c) for c in cases]
    ledger.verify("iv-001", later_episodes=later, guardrail_episodes=later,
                  min_guardrail_success=0.75)
    print("verify 后:", iv.status, "| search 资产:",
          assets.get("search").evidence.name,
          "score =", assets.get("search").score)
    print(json.dumps(ledger.summary(), ensure_ascii=False))

    if not gate_report.passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
