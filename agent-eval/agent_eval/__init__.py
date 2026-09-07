"""agent_eval — Agent workflow 评测系统参考实现（纯标准库，零依赖）。

五个阶段对应五个模块：
- tracing   阶段1 观测地基：trace / span / 版本标签 / token 成本
- episode   阶段2 评审单元：Task Episode + 验收标准
- metrics   阶段3 分层指标：结果 / 轨迹 / 步骤 / 资产 / 系统
- evaluators + dataset  阶段4 评测数据集与执行器
- gate + learning       阶段5 CI 门禁与迭代闭环
"""

from .tracing import Tracer, Trace, Span, VersionTags
from .episode import TaskEpisode, AcceptanceCriterion, Rubric
from .metrics import (
    EvidenceLevel,
    AssetLedger,
    outcome_metrics,
    trajectory_metrics,
    step_metrics,
    system_metrics,
)
from .dataset import GoldenCase, load_golden_set, save_golden_set
from .evaluators import (
    DeterministicEvaluator,
    TrajectoryEvaluator,
    LLMJudge,
    EvalResult,
    EvalRunner,
)
from .gate import Gate, GateConfig, GateReport
from .learning import LearningLedger, Intervention

__all__ = [
    "Tracer", "Trace", "Span", "VersionTags",
    "TaskEpisode", "AcceptanceCriterion", "Rubric",
    "EvidenceLevel", "AssetLedger",
    "outcome_metrics", "trajectory_metrics", "step_metrics", "system_metrics",
    "GoldenCase", "load_golden_set", "save_golden_set",
    "DeterministicEvaluator", "TrajectoryEvaluator", "LLMJudge",
    "EvalResult", "EvalRunner",
    "Gate", "GateConfig", "GateReport",
    "LearningLedger", "Intervention",
]
