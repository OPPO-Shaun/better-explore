"""阶段3 分层量化指标。

- 结果层（Outcome）：任务成功率、验收标准通过率、人工/用户满意度
- 轨迹层（Trajectory）：步数偏差、多余循环/重试、错误恢复率、计划遵循度
- 步骤层（Step）：工具选择正确率、参数合法率、路由决策准确率
- 资产层（Asset，借鉴 Better Harness）：
  "配置(Present) → 被路由到(Wired) → 被真实使用(Exercised) → 带来可对比改善(Outcome-supported)"
  四级证据，证据等级是分数上限（封顶），不是计分公式。
- 系统层（System）：端到端延迟、单任务成本、失败率、人工介入率
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Optional

from .episode import TaskEpisode
from .tracing import Trace


# ---------------------------------------------------------------- 结果层

def outcome_metrics(episodes: list[TaskEpisode],
                    satisfaction: Optional[dict[str, float]] = None) -> dict[str, Any]:
    """任务成功率、验收标准通过率、满意度均值。

    satisfaction: episode_id -> 人工/用户满意度评分（可选）。
    """
    if not episodes:
        return {"task_success_rate": 0.0, "criteria_pass_rate": 0.0,
                "satisfaction_avg": None, "n_episodes": 0}
    successes = sum(1 for e in episodes if e.succeeded)
    all_criteria: list[bool] = []
    for e in episodes:
        all_criteria.extend(e.acceptance_results().values())
    sat = None
    if satisfaction:
        vals = [satisfaction[e.episode_id] for e in episodes
                if e.episode_id in satisfaction]
        sat = sum(vals) / len(vals) if vals else None
    return {
        "task_success_rate": successes / len(episodes),
        "criteria_pass_rate": (sum(all_criteria) / len(all_criteria)
                               if all_criteria else 0.0),
        "satisfaction_avg": sat,
        "n_episodes": len(episodes),
    }


# ---------------------------------------------------------------- 轨迹层

def _actual_steps(trace: Trace) -> list[str]:
    """从 trace 中提取动作序列（工具名或节点名，按时间排序）。"""
    steps = sorted(
        (s for s in trace.spans if s.kind in ("tool", "node")),
        key=lambda s: s.start_time,
    )
    return [s.tool_name or s.name for s in steps]


def trajectory_metrics(episode: TaskEpisode) -> dict[str, Any]:
    """步数偏差、多余重试、错误恢复率、计划遵循度（参考轨迹匹配）。"""
    trace = episode.trace
    if trace is None:
        return {"available": False}
    actual = _actual_steps(trace)
    ref = episode.reference_trajectory
    errors = trace.errors()
    # 错误恢复率：出错的 span 之后是否有同名成功的 span
    recovered = 0
    for err in errors:
        recovered += any(
            s.name == err.name and not s.error and s.start_time > err.start_time
            for s in trace.spans
        )
    # 计划遵循度：参考轨迹作为子序列出现在实际序列中的比例（LCS 风格贪心）
    adherence = None
    if ref:
        it = iter(actual)
        matched = sum(1 for step in ref if step in it)
        adherence = matched / len(ref)
    return {
        "available": True,
        "n_steps": len(actual),
        "step_deviation": (len(actual) - len(ref)) if ref else None,
        "total_retries": trace.total_retries(),
        "n_errors": len(errors),
        "error_recovery_rate": (recovered / len(errors)) if errors else 1.0,
        "plan_adherence": adherence,
        "actual_trajectory": actual,
    }


# ---------------------------------------------------------------- 步骤层

def step_metrics(episode: TaskEpisode,
                 expected_tools: Optional[list[str]] = None,
                 arg_validator: Optional[Callable[[str, Any], bool]] = None
                 ) -> dict[str, Any]:
    """工具选择正确率、参数合法率。

    expected_tools: 本任务允许/期望使用的工具集合
    arg_validator: (tool_name, args) -> bool 的参数合法性校验
    """
    trace = episode.trace
    if trace is None:
        return {"available": False}
    calls = trace.tool_calls()
    if not calls:
        return {"available": True, "n_tool_calls": 0,
                "tool_selection_accuracy": None, "arg_validity_rate": None}
    sel = None
    if expected_tools is not None:
        allowed = set(expected_tools)
        sel = sum(1 for c in calls if c.tool_name in allowed) / len(calls)
    argv = None
    if arg_validator is not None:
        argv = sum(1 for c in calls
                   if arg_validator(c.tool_name or "", c.tool_args)) / len(calls)
    return {
        "available": True,
        "n_tool_calls": len(calls),
        "tool_selection_accuracy": sel,
        "arg_validity_rate": argv,
    }


# ---------------------------------------------------------------- 资产层

class EvidenceLevel(IntEnum):
    """Better Harness 式四级证据（外加缺证状态）。"""

    UNOBSERVED = 0        # 缺证 / 未观察到
    PRESENT = 1           # 已配置（资产存在）
    WIRED = 2             # 被路由到（路由/触发器可达）
    EXERCISED = 3         # 被真实使用（任务中被调用并留下结果）
    OUTCOME_SUPPORTED = 4  # 有后续可对比结果证明改善


#: 证据等级 → 分数上限（封顶，不是计分公式）
SCORE_CEILING: dict[EvidenceLevel, int] = {
    EvidenceLevel.UNOBSERVED: 59,
    EvidenceLevel.PRESENT: 74,
    EvidenceLevel.WIRED: 84,
    EvidenceLevel.EXERCISED: 94,
    EvidenceLevel.OUTCOME_SUPPORTED: 100,
}


@dataclass
class AssetRecord:
    """一项 agent 资产（prompt / Skill / 工具定义 / 规则文件）的证据台账。"""

    asset_id: str
    kind: str  # "prompt" | "skill" | "tool" | "rule"
    evidence: EvidenceLevel = EvidenceLevel.UNOBSERVED
    raw_score: int = 0  # 评审者依据证据给出的原始分
    notes: list[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        """有效分 = min(原始分, 证据等级上限)。配置≠使用，虚高被封顶。"""
        return min(self.raw_score, SCORE_CEILING[self.evidence])


class AssetLedger:
    """资产台账：登记资产、根据 trace 自动推进证据等级、汇总评分。"""

    def __init__(self) -> None:
        self._assets: dict[str, AssetRecord] = {}

    def register(self, asset_id: str, kind: str, raw_score: int = 100) -> AssetRecord:
        rec = AssetRecord(asset_id=asset_id, kind=kind,
                          evidence=EvidenceLevel.PRESENT, raw_score=raw_score)
        rec.notes.append("registered (Present)")
        self._assets[asset_id] = rec
        return rec

    def get(self, asset_id: str) -> AssetRecord:
        return self._assets[asset_id]

    def mark(self, asset_id: str, level: EvidenceLevel, note: str = "") -> None:
        """只升不降：证据等级单调推进。"""
        rec = self._assets[asset_id]
        if level > rec.evidence:
            rec.evidence = level
            if note:
                rec.notes.append(note)

    def observe_trace(self, trace: Trace,
                      tool_asset_map: Optional[dict[str, str]] = None) -> None:
        """从 trace 中自动推进证据：工具被真实调用 → Exercised。

        tool_asset_map: tool_name -> asset_id 的映射；缺省时按同名匹配。
        """
        mapping = tool_asset_map or {}
        for call in trace.tool_calls():
            name = call.tool_name or ""
            asset_id = mapping.get(name, name)
            if asset_id in self._assets and not call.error:
                self.mark(asset_id, EvidenceLevel.EXERCISED,
                          f"exercised in trace {trace.trace_id}")

    def mark_outcome_supported(self, asset_id: str, note: str) -> None:
        """只有后续可对比窗口证明改善（无 guardrail 回归）才调用此方法。"""
        self.mark(asset_id, EvidenceLevel.OUTCOME_SUPPORTED, note)

    def summary(self) -> dict[str, Any]:
        assets = list(self._assets.values())
        dist: dict[str, int] = {}
        for level in EvidenceLevel:
            dist[level.name] = sum(1 for a in assets if a.evidence == level)
        return {
            "n_assets": len(assets),
            "evidence_distribution": dist,
            "assets": [
                {"asset_id": a.asset_id, "kind": a.kind,
                 "evidence": a.evidence.name, "score": a.score}
                for a in assets
            ],
        }


# ---------------------------------------------------------------- 系统层

def system_metrics(episodes: list[TaskEpisode]) -> dict[str, Any]:
    """端到端延迟、单任务成本、失败率、人工介入率。"""
    traces = [e.trace for e in episodes if e.trace is not None]
    if not traces:
        return {"available": False}
    n = len(episodes)
    return {
        "available": True,
        "avg_latency_ms": sum(t.duration_ms for t in traces) / len(traces),
        "avg_cost_usd": sum(t.total_cost_usd for t in traces) / len(traces),
        "avg_tokens": sum(t.total_tokens for t in traces) / len(traces),
        "failure_rate": sum(1 for e in episodes if not e.succeeded) / n,
        "human_intervention_rate": sum(1 for e in episodes
                                       if e.human_intervened) / n,
    }
