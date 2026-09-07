"""阶段4 评测执行器。

评测器组合（优先级从高到低）：
1. DeterministicEvaluator —— 确定性断言（便宜、稳定）
2. TrajectoryEvaluator   —— 参考轨迹匹配（agentevals 风格：strict / unordered / subset / superset）
3. LLMJudge              —— LLM-as-a-Judge 接口（可接 DeepEval / EvalScope / 任意模型），
                             需定期抽样人工标注校准
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .dataset import GoldenCase
from .episode import AcceptanceCriterion, TaskEpisode
from .metrics import _actual_steps
from .tracing import Trace


@dataclass
class EvalResult:
    """单条用例的评测结果。"""

    case_id: str
    evaluator: str
    passed: bool
    score: float  # 0.0 - 1.0
    details: dict[str, Any] = field(default_factory=dict)


class DeterministicEvaluator:
    """确定性断言评测器：运行用例中定义的验收标准。"""

    name = "deterministic"

    def evaluate(self, case: GoldenCase, episode: TaskEpisode) -> EvalResult:
        criteria = [
            AcceptanceCriterion(
                criterion_id=c["criterion_id"],
                description=c.get("description", ""),
                kind=c.get("kind", "exact_match"),
                expected=c.get("expected"),
            )
            for c in case.acceptance
        ]
        trace = episode.trace
        results = {
            c.criterion_id: (trace is not None
                             and c.evaluate(trace, episode.final_output))
            for c in criteria
        }
        n = len(results)
        passed_n = sum(results.values())
        return EvalResult(
            case_id=case.case_id,
            evaluator=self.name,
            passed=n > 0 and passed_n == n,
            score=(passed_n / n) if n else 0.0,
            details={"criteria": results},
        )


class TrajectoryEvaluator:
    """参考轨迹匹配评测器（agentevals 风格）。

    mode:
    - "strict":    实际轨迹与参考轨迹完全一致
    - "unordered": 实际轨迹恰好是参考轨迹的一个排列（多重集相等）
    - "subset":    实际步骤都在参考轨迹允许范围内（不做多余动作）
    - "superset":  参考轨迹的每一步都被执行（允许额外步骤）
    """

    name = "trajectory"

    def __init__(self, mode: str = "superset"):
        if mode not in ("strict", "unordered", "subset", "superset"):
            raise ValueError(f"未知匹配模式: {mode}")
        self.mode = mode

    def evaluate(self, case: GoldenCase, episode: TaskEpisode) -> EvalResult:
        ref = case.reference_trajectory
        trace = episode.trace
        if not ref or trace is None:
            return EvalResult(case.case_id, f"{self.name}:{self.mode}",
                              passed=True, score=1.0,
                              details={"skipped": "无参考轨迹或无 trace"})
        actual = _actual_steps(trace)
        if self.mode == "strict":
            passed = actual == ref
        elif self.mode == "unordered":
            passed = sorted(actual) == sorted(ref)
        elif self.mode == "subset":
            passed = set(actual) <= set(ref)
        else:  # superset
            passed = set(ref) <= set(actual)
        # 分数：参考步骤按序被覆盖的比例
        it = iter(actual)
        matched = sum(1 for step in ref if step in it)
        return EvalResult(
            case_id=case.case_id,
            evaluator=f"{self.name}:{self.mode}",
            passed=passed,
            score=matched / len(ref),
            details={"reference": ref, "actual": actual},
        )


#: judge_fn 签名: (case, episode) -> (score_0_1, reasoning)
JudgeFn = Callable[[GoldenCase, TaskEpisode], tuple[float, str]]


class LLMJudge:
    """LLM-as-a-Judge 接口。

    judge_fn 由调用方注入（可封装 DeepEval / EvalScope / 任意模型 API），
    本模块不绑定任何模型依赖。校准：定期把 judge 结果与人工标注对比，
    用 record_human_label / calibration_report 监控偏差。
    """

    name = "llm_judge"

    def __init__(self, judge_fn: JudgeFn, pass_threshold: float = 0.7):
        self.judge_fn = judge_fn
        self.pass_threshold = pass_threshold
        self._human_labels: dict[str, float] = {}
        self._judge_scores: dict[str, float] = {}

    def evaluate(self, case: GoldenCase, episode: TaskEpisode) -> EvalResult:
        score, reasoning = self.judge_fn(case, episode)
        score = max(0.0, min(1.0, score))
        self._judge_scores[case.case_id] = score
        return EvalResult(
            case_id=case.case_id,
            evaluator=self.name,
            passed=score >= self.pass_threshold,
            score=score,
            details={"reasoning": reasoning,
                     "rubric_dimensions": case.rubric_dimensions},
        )

    def record_human_label(self, case_id: str, score: float) -> None:
        """记录人工标注分（0-1），用于校准 judge。"""
        self._human_labels[case_id] = max(0.0, min(1.0, score))

    def calibration_report(self) -> dict[str, Any]:
        """judge 与人工标注的平均绝对偏差；偏差大则需要重校 rubric/judge。"""
        common = set(self._human_labels) & set(self._judge_scores)
        if not common:
            return {"n_labeled": 0, "mean_abs_error": None}
        errs = [abs(self._judge_scores[c] - self._human_labels[c]) for c in common]
        return {"n_labeled": len(common),
                "mean_abs_error": sum(errs) / len(errs)}


class EvalRunner:
    """把 workflow 跑一遍评测集并汇总结果。

    run_workflow: (case) -> TaskEpisode，由调用方提供（真实运行你的 agent）。
    """

    def __init__(self, evaluators: list[Any]):
        self.evaluators = evaluators

    def run(self, cases: list[GoldenCase],
            run_workflow: Callable[[GoldenCase], TaskEpisode]
            ) -> dict[str, Any]:
        results: list[EvalResult] = []
        episodes: list[TaskEpisode] = []
        for case in cases:
            episode = run_workflow(case)
            episodes.append(episode)
            for ev in self.evaluators:
                results.append(ev.evaluate(case, episode))
        by_evaluator: dict[str, list[EvalResult]] = {}
        for r in results:
            by_evaluator.setdefault(r.evaluator, []).append(r)
        summary = {
            name: {
                "pass_rate": sum(1 for r in rs if r.passed) / len(rs),
                "avg_score": sum(r.score for r in rs) / len(rs),
                "n": len(rs),
            }
            for name, rs in by_evaluator.items()
        }
        return {"summary": summary, "results": results, "episodes": episodes}
