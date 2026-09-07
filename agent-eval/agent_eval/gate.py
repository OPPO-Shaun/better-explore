"""阶段5 CI 门禁。

每次改 prompt/模型/工具/拓扑：跑离线回归集 → 与阈值和基线对比 → 不达标不上线。
基线（baseline）保存为 JSON，供下次对比与 A/B。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .episode import TaskEpisode
from .metrics import outcome_metrics, system_metrics
from .tracing import VersionTags


@dataclass
class GateConfig:
    """门禁阈值配置。"""

    min_task_success_rate: float = 0.9
    min_criteria_pass_rate: float = 0.9
    max_avg_cost_usd: Optional[float] = None
    max_avg_latency_ms: Optional[float] = None
    # 相对基线的最大允许回归幅度（成功率下降超过此值即失败）
    max_success_regression: float = 0.02


@dataclass
class GateReport:
    """门禁结果。"""

    passed: bool
    version_tags: dict[str, str]
    metrics: dict[str, Any]
    checks: dict[str, bool] = field(default_factory=dict)
    baseline_comparison: Optional[dict[str, Any]] = None

    def to_json(self, **kw: Any) -> str:
        return json.dumps(
            {"passed": self.passed, "version_tags": self.version_tags,
             "metrics": self.metrics, "checks": self.checks,
             "baseline_comparison": self.baseline_comparison},
            ensure_ascii=False, **kw)


class Gate:
    """离线回归门禁：阈值检查 + 基线对比。"""

    def __init__(self, config: GateConfig, baseline_path: str | Path):
        self.config = config
        self.baseline_path = Path(baseline_path)

    def load_baseline(self) -> Optional[dict[str, Any]]:
        if self.baseline_path.exists():
            return json.loads(self.baseline_path.read_text(encoding="utf-8"))
        return None

    def save_baseline(self, report: GateReport) -> None:
        """仅在门禁通过后，把本次结果固化为新基线。"""
        if not report.passed:
            raise ValueError("不允许把未通过门禁的结果保存为基线")
        self.baseline_path.parent.mkdir(parents=True, exist_ok=True)
        self.baseline_path.write_text(report.to_json(indent=2), encoding="utf-8")

    def check(self, episodes: list[TaskEpisode],
              version_tags: VersionTags) -> GateReport:
        out = outcome_metrics(episodes)
        sys = system_metrics(episodes)
        cfg = self.config
        checks: dict[str, bool] = {
            "task_success_rate": out["task_success_rate"] >= cfg.min_task_success_rate,
            "criteria_pass_rate": out["criteria_pass_rate"] >= cfg.min_criteria_pass_rate,
        }
        if cfg.max_avg_cost_usd is not None and sys.get("available"):
            checks["avg_cost_usd"] = sys["avg_cost_usd"] <= cfg.max_avg_cost_usd
        if cfg.max_avg_latency_ms is not None and sys.get("available"):
            checks["avg_latency_ms"] = sys["avg_latency_ms"] <= cfg.max_avg_latency_ms

        baseline = self.load_baseline()
        comparison = None
        if baseline is not None:
            base_rate = baseline["metrics"]["outcome"]["task_success_rate"]
            delta = out["task_success_rate"] - base_rate
            checks["no_success_regression"] = delta >= -cfg.max_success_regression
            comparison = {
                "baseline_version_tags": baseline.get("version_tags"),
                "baseline_task_success_rate": base_rate,
                "delta_task_success_rate": delta,
            }

        return GateReport(
            passed=all(checks.values()),
            version_tags=version_tags.as_dict(),
            metrics={"outcome": out, "system": sys},
            checks=checks,
            baseline_comparison=comparison,
        )
