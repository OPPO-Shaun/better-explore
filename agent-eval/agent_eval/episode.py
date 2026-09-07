"""阶段2 评审单元与成功标准。

借鉴 Better Harness 的 Task Episode 思路：
- 评审单元 = 一个目标 + 一个验收边界（可跨多轮 session，但绑定同一目标）
- 判定方式：可自动验证的（断言）优先；开放式输出使用 rubric 打分
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .tracing import Trace


@dataclass
class AcceptanceCriterion:
    """一条可自动验证的验收标准。

    kind:
    - "assertion": check(trace, output) -> bool 的确定性断言
    - "exact_match": 输出与 expected 精确匹配
    - "contains": 输出包含 expected 子串
    - "structure": 输出为 dict 且包含 expected 中列出的全部键
    """

    criterion_id: str
    description: str
    kind: str = "assertion"
    expected: Any = None
    check: Optional[Callable[[Trace, Any], bool]] = None

    def evaluate(self, trace: Trace, output: Any) -> bool:
        if self.kind == "assertion":
            if self.check is None:
                raise ValueError(f"{self.criterion_id}: assertion 需要 check 函数")
            return bool(self.check(trace, output))
        if self.kind == "exact_match":
            return output == self.expected
        if self.kind == "contains":
            return isinstance(output, str) and str(self.expected) in output
        if self.kind == "structure":
            return isinstance(output, dict) and all(
                k in output for k in (self.expected or [])
            )
        raise ValueError(f"未知的验收标准类型: {self.kind}")


@dataclass
class Rubric:
    """开放式输出的评分标准，供 LLM-as-a-Judge 或人工评分使用。"""

    rubric_id: str
    dimensions: list[str]  # 例如 ["正确性", "忠实性", "有用性"]
    scale: tuple[int, int] = (1, 5)
    guidance: str = ""


@dataclass
class TaskEpisode:
    """一个目标 + 一个验收边界的评审单元。"""

    episode_id: str
    goal: str
    task_type: str  # 任务类别，对应黄金集分类
    acceptance: list[AcceptanceCriterion] = field(default_factory=list)
    rubric: Optional[Rubric] = None
    reference_trajectory: list[str] = field(default_factory=list)  # 理想工具/节点序列
    traces: list[Trace] = field(default_factory=list)
    final_output: Any = None
    human_intervened: bool = False

    def add_trace(self, trace: Trace) -> None:
        self.traces.append(trace)

    @property
    def trace(self) -> Optional[Trace]:
        """Episode 的最终（最新）trace。"""
        return self.traces[-1] if self.traces else None

    def acceptance_results(self) -> dict[str, bool]:
        """逐条运行验收标准。"""
        if self.trace is None:
            return {c.criterion_id: False for c in self.acceptance}
        return {
            c.criterion_id: c.evaluate(self.trace, self.final_output)
            for c in self.acceptance
        }

    @property
    def succeeded(self) -> bool:
        """全部验收标准通过才算任务成功。"""
        results = self.acceptance_results()
        return bool(results) and all(results.values())
