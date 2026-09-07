"""阶段1 观测地基：为 workflow 每次运行记录完整 trace。

设计对齐 OpenTelemetry 的 trace/span 概念，输出为 JSON，可直接
映射/导出到 Langfuse、Phoenix 等自托管平台（它们均支持 OTel 语义）。

每条 Trace 记录：
- 每个节点（span）的输入/输出
- 工具调用及参数、模型调用及 token 用量与成本
- 错误与重试
- 耗时
- 版本标签（prompt / model / tool 定义 / workflow 拓扑）——A/B 与回归的前提
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass(frozen=True)
class VersionTags:
    """每次运行必须携带的版本标签，用于 A/B 对比与回归归因。"""

    prompt_version: str
    model_version: str
    tool_defs_version: str
    workflow_version: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class Span:
    """一个 workflow 节点 / 工具调用 / 模型调用的观测单元。"""

    span_id: str
    trace_id: str
    name: str
    kind: str  # "node" | "tool" | "llm"
    parent_id: Optional[str] = None
    inputs: Any = None
    outputs: Any = None
    start_time: float = 0.0
    end_time: float = 0.0
    error: Optional[str] = None
    retries: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)
    # llm spans
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    # tool spans
    tool_name: Optional[str] = None
    tool_args: Any = None

    @property
    def duration_ms(self) -> float:
        return max(0.0, (self.end_time - self.start_time) * 1000)


@dataclass
class Trace:
    """一次 workflow 运行的完整轨迹。"""

    trace_id: str
    task_id: str
    version_tags: VersionTags
    spans: list[Span] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return max(0.0, (self.end_time - self.start_time) * 1000)

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self.spans)

    @property
    def total_tokens(self) -> int:
        return sum(s.input_tokens + s.output_tokens for s in self.spans)

    def tool_calls(self) -> list[Span]:
        return [s for s in self.spans if s.kind == "tool"]

    def llm_calls(self) -> list[Span]:
        return [s for s in self.spans if s.kind == "llm"]

    def errors(self) -> list[Span]:
        return [s for s in self.spans if s.error]

    def total_retries(self) -> int:
        return sum(s.retries for s in self.spans)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["duration_ms"] = self.duration_ms
        d["total_cost_usd"] = self.total_cost_usd
        d["total_tokens"] = self.total_tokens
        return d

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kwargs)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Trace":
        tags = VersionTags(**d["version_tags"])
        span_fields = {f for f in Span.__dataclass_fields__}
        spans = [
            Span(**{k: v for k, v in s.items() if k in span_fields})
            for s in d.get("spans", [])
        ]
        return cls(
            trace_id=d["trace_id"],
            task_id=d["task_id"],
            version_tags=tags,
            spans=spans,
            start_time=d.get("start_time", 0.0),
            end_time=d.get("end_time", 0.0),
            metadata=d.get("metadata", {}),
        )


class Tracer:
    """采集器：在 workflow 代码中埋点使用。

    用法::

        tracer = Tracer(task_id="t-1", version_tags=tags)
        with tracer.span("plan", kind="node", inputs=goal) as sp:
            sp.outputs = plan
        tracer.record_tool_call("search", args={"q": "..."}, result=r)
        tracer.record_llm_call("gpt-x", prompt=p, completion=c,
                               input_tokens=100, output_tokens=20,
                               cost_usd=0.001)
        trace = tracer.finish()
    """

    def __init__(self, task_id: str, version_tags: VersionTags,
                 metadata: Optional[dict[str, Any]] = None):
        self.trace = Trace(
            trace_id=uuid.uuid4().hex,
            task_id=task_id,
            version_tags=version_tags,
            start_time=time.time(),
            metadata=metadata or {},
        )
        self._stack: list[str] = []

    def span(self, name: str, kind: str = "node", inputs: Any = None) -> "_SpanCtx":
        return _SpanCtx(self, name, kind, inputs)

    def record_tool_call(self, tool_name: str, args: Any = None,
                         result: Any = None, error: Optional[str] = None,
                         retries: int = 0, duration_ms: float = 0.0) -> Span:
        now = time.time()
        sp = Span(
            span_id=uuid.uuid4().hex, trace_id=self.trace.trace_id,
            name=f"tool:{tool_name}", kind="tool",
            parent_id=self._stack[-1] if self._stack else None,
            inputs=args, outputs=result, error=error, retries=retries,
            start_time=now - duration_ms / 1000, end_time=now,
            tool_name=tool_name, tool_args=args,
        )
        self.trace.spans.append(sp)
        return sp

    def record_llm_call(self, model: str, prompt: Any = None,
                        completion: Any = None, input_tokens: int = 0,
                        output_tokens: int = 0, cost_usd: float = 0.0,
                        error: Optional[str] = None, retries: int = 0,
                        duration_ms: float = 0.0) -> Span:
        now = time.time()
        sp = Span(
            span_id=uuid.uuid4().hex, trace_id=self.trace.trace_id,
            name=f"llm:{model}", kind="llm",
            parent_id=self._stack[-1] if self._stack else None,
            inputs=prompt, outputs=completion, error=error, retries=retries,
            start_time=now - duration_ms / 1000, end_time=now,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cost_usd=cost_usd, attributes={"model": model},
        )
        self.trace.spans.append(sp)
        return sp

    def finish(self) -> Trace:
        self.trace.end_time = time.time()
        return self.trace


class _SpanCtx:
    def __init__(self, tracer: Tracer, name: str, kind: str, inputs: Any):
        self._tracer = tracer
        self.span = Span(
            span_id=uuid.uuid4().hex,
            trace_id=tracer.trace.trace_id,
            name=name, kind=kind, inputs=inputs,
            parent_id=tracer._stack[-1] if tracer._stack else None,
        )

    def __enter__(self) -> Span:
        self.span.start_time = time.time()
        self._tracer._stack.append(self.span.span_id)
        return self.span

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.span.end_time = time.time()
        if exc is not None:
            self.span.error = f"{exc_type.__name__}: {exc}"
        self._tracer._stack.pop()
        self._tracer.trace.spans.append(self.span)
        return False
