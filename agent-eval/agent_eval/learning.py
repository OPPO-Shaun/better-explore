"""阶段5 迭代闭环：Learning Capture 台账（借鉴 Better Harness）。

- "修复—验证"分离：改进（Intervention）登记后状态只是 applied，
  不立刻宣布分数提升；必须由**后续**可对比的真实任务窗口证明改善
  （成功率不降、无 guardrail 回归）才能标记 verified。
- Learning Capture 飞轮：重复失败模式 → 沉淀为可复用资产 → 跟踪
  资产是否真的被后续任务使用和受益 → 再评分。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from .episode import TaskEpisode
from .metrics import AssetLedger, outcome_metrics


@dataclass
class Intervention:
    """一次改进（修复某个 finding / 沉淀某项资产）。

    状态机: proposed -> applied -> verified | regressed
    """

    intervention_id: str
    description: str
    target_asset_id: Optional[str] = None  # 沉淀/修改的资产
    failure_pattern: str = ""  # 触发本次改进的重复失败模式
    status: str = "proposed"
    baseline_success_rate: Optional[float] = None  # 应用前窗口的成功率
    verified_success_rate: Optional[float] = None  # 后续对比窗口的成功率
    notes: list[str] = field(default_factory=list)


class LearningLedger:
    """干预台账：登记改进、用后续窗口验证、驱动资产层再评分。"""

    def __init__(self, asset_ledger: Optional[AssetLedger] = None,
                 path: Optional[str | Path] = None):
        self.asset_ledger = asset_ledger
        self.path = Path(path) if path else None
        self._interventions: dict[str, Intervention] = {}
        if self.path and self.path.exists():
            for d in json.loads(self.path.read_text(encoding="utf-8")):
                self._interventions[d["intervention_id"]] = Intervention(**d)

    def get(self, intervention_id: str) -> Intervention:
        return self._interventions[intervention_id]

    def propose(self, intervention: Intervention) -> Intervention:
        intervention.status = "proposed"
        self._interventions[intervention.intervention_id] = intervention
        self._persist()
        return intervention

    def apply(self, intervention_id: str,
              baseline_episodes: list[TaskEpisode]) -> Intervention:
        """记录改进已应用，同时锁定应用前窗口的基线成功率。

        注意：此时不更新任何有效性评分——修复状态 ≠ 后续有效性。
        """
        iv = self._interventions[intervention_id]
        iv.status = "applied"
        iv.baseline_success_rate = outcome_metrics(
            baseline_episodes)["task_success_rate"]
        iv.notes.append(f"applied; baseline={iv.baseline_success_rate:.3f}")
        self._persist()
        return iv

    def verify(self, intervention_id: str,
               later_episodes: list[TaskEpisode],
               guardrail_episodes: Optional[list[TaskEpisode]] = None,
               min_guardrail_success: float = 1.0) -> Intervention:
        """用**后续**可对比任务窗口验证改进是否真的生效。

        - later_episodes: 应用改进之后的真实任务窗口
        - guardrail_episodes: 守护回归集（不允许因本次改进而变差）
        只有"后续窗口成功率不低于基线 且 guardrail 无回归"才 verified，
        并且此时才推进资产的 Outcome-supported 证据。
        """
        iv = self._interventions[intervention_id]
        if iv.status != "applied":
            raise ValueError(f"{intervention_id} 尚未 applied，不能验证")
        later = outcome_metrics(later_episodes)["task_success_rate"]
        iv.verified_success_rate = later
        guardrail_ok = True
        if guardrail_episodes:
            g = outcome_metrics(guardrail_episodes)["task_success_rate"]
            guardrail_ok = g >= min_guardrail_success
            iv.notes.append(f"guardrail success={g:.3f} ok={guardrail_ok}")
        improved = (iv.baseline_success_rate is not None
                    and later >= iv.baseline_success_rate)
        if improved and guardrail_ok:
            iv.status = "verified"
            iv.notes.append(f"verified; later={later:.3f}")
            # 只有此刻才允许资产升到 Outcome-supported
            if self.asset_ledger and iv.target_asset_id:
                self.asset_ledger.mark_outcome_supported(
                    iv.target_asset_id,
                    f"verified by intervention {iv.intervention_id}")
        else:
            iv.status = "regressed"
            iv.notes.append(f"regressed; later={later:.3f}")
        self._persist()
        return iv

    def discover(self, failed_episodes: list[TaskEpisode],
                 min_occurrences: int = 2) -> list[str]:
        """检测重复失败模式：同一 task_type 反复失败 → 候选沉淀点。"""
        counts: dict[str, int] = {}
        for e in failed_episodes:
            if not e.succeeded:
                counts[e.task_type] = counts.get(e.task_type, 0) + 1
        return [t for t, n in counts.items() if n >= min_occurrences]

    def summary(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for iv in self._interventions.values():
            by_status[iv.status] = by_status.get(iv.status, 0) + 1
        return {"n_interventions": len(self._interventions),
                "by_status": by_status}

    def _persist(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps([asdict(iv) for iv in self._interventions.values()],
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
