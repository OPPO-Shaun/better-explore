"""阶段4 评测数据集。

三个来源，统一为 GoldenCase（JSONL 持久化）：
- golden:     人工黄金集（每类任务 20–50 条起步）
- synthetic:  合成边界用例
- regression: 生产失败案例回流（每个线上失败沉淀为一条回归用例）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

VALID_SOURCES = ("golden", "synthetic", "regression")


@dataclass
class GoldenCase:
    """一条评测用例。"""

    case_id: str
    task_type: str
    goal: str
    source: str = "golden"  # golden | synthetic | regression
    inputs: Any = None
    expected_output: Any = None
    acceptance: list[dict[str, Any]] = field(default_factory=list)
    # 例：[{"criterion_id": "c1", "kind": "contains", "expected": "42",
    #       "description": "答案包含 42"}]
    reference_trajectory: list[str] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    rubric_dimensions: list[str] = field(default_factory=list)
    origin: Optional[str] = None  # regression 用例的来源（线上 trace id 等）

    def __post_init__(self) -> None:
        if self.source not in VALID_SOURCES:
            raise ValueError(f"source 必须是 {VALID_SOURCES} 之一: {self.source}")


def load_golden_set(path: str | Path) -> list[GoldenCase]:
    """从 JSONL 文件加载评测集。"""
    cases: list[GoldenCase] = []
    fields = set(GoldenCase.__dataclass_fields__)
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            d = json.loads(line)
            cases.append(GoldenCase(**{k: v for k, v in d.items() if k in fields}))
    return cases


def save_golden_set(cases: list[GoldenCase], path: str | Path) -> None:
    """保存评测集为 JSONL。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")


def add_regression_case(path: str | Path, case: GoldenCase) -> None:
    """失败案例回流：把一个生产失败沉淀为回归用例（追加写入）。"""
    case.source = "regression"
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(case), ensure_ascii=False) + "\n")
