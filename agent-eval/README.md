# agent-eval — Agent Workflow 评测系统参考实现

按五阶段计划实现的 agent workflow 评测框架。**纯 Python 标准库，零第三方依赖**，可直接运行，也可作为接入 Langfuse / Phoenix / DeepEval / EvalScope 等工具前的骨架参考。

## 快速开始

```bash
cd agent-eval
python -m unittest discover -s tests -v   # 单元测试
python examples/demo.py                   # 端到端五阶段演示
# 或从仓库根目录跑 CI 门禁：
bash scripts/agent-eval-gate.sh
```

## 五阶段与模块映射

| 阶段 | 模块 | 内容 |
| --- | --- | --- |
| 1. 观测地基 | `agent_eval/tracing.py` | OTel 风格 `Tracer/Trace/Span`：节点输入输出、工具调用及参数、模型调用与 token 成本、错误与重试、耗时；每次运行强制携带 `VersionTags`（prompt/模型/工具定义/workflow 拓扑四个版本标签），JSON 可导出到 Langfuse/Phoenix |
| 2. 评审单元 | `agent_eval/episode.py` | `TaskEpisode`（一个目标 + 一个验收边界）；`AcceptanceCriterion` 确定性验收（断言/精确匹配/包含/结构）；`Rubric` 供开放式输出评分 |
| 3. 分层指标 | `agent_eval/metrics.py` | 结果层（成功率/验收通过率/满意度）、轨迹层（步数偏差/重试/错误恢复率/计划遵循度）、步骤层（工具选择正确率/参数合法率）、**资产层**（Better Harness 式四级证据 Present→Wired→Exercised→Outcome-supported，证据等级封顶分数 74/84/94/100）、系统层（延迟/成本/失败率/人工介入率） |
| 4. 数据集与执行器 | `agent_eval/dataset.py`、`agent_eval/evaluators.py` | 黄金集 JSONL（golden/synthetic/regression 三来源，失败案例回流追加）；`DeterministicEvaluator`（断言优先）、`TrajectoryEvaluator`（strict/unordered/subset/superset 参考轨迹匹配，agentevals 风格）、`LLMJudge`（注入式 judge 接口 + 人工标注校准报告）、`EvalRunner` 汇总 |
| 5. 迭代闭环 | `agent_eval/gate.py`、`agent_eval/learning.py` | `Gate` CI 门禁（阈值 + 基线对比，回归超限即失败，仅通过者可固化为新基线）；`LearningLedger` 修复—验证分离（Intervention 状态机 proposed→applied→verified/regressed，**只有后续可对比窗口证明改善且 guardrail 无回归，资产才升 Outcome-supported**）、重复失败模式发现 |

## 核心设计原则（借鉴 Better Harness）

1. **配置 ≠ 使用**：登记的资产初始只是 `Present`（分数封顶 74）；只有 trace 中观察到被真实调用才升 `Exercised`（封顶 94）。
2. **修复 ≠ 生效**：改进应用后（applied）不涨分；必须用应用之后的真实任务窗口对比基线，成功率不降且守护集无回归，才 `verified` 并允许资产升 `Outcome-supported`（封顶 100）。
3. **证据封顶，不是计分公式**：`score = min(原始评分, 证据等级上限)`，杜绝"配置即得分"的虚高。

## 接入你自己的 workflow

1. 在 workflow 代码中用 `Tracer` 埋点（或写适配器把已有的 Langfuse/OTel trace 转成 `Trace.from_dict`）。
2. 把每类任务写成 `GoldenCase` 存入 `datasets/` 下的 JSONL（每类 20–50 条起步；线上失败用 `add_regression_case` 回流）。
3. 实现 `run_workflow(case) -> TaskEpisode`，交给 `EvalRunner`。
4. `LLMJudge` 的 `judge_fn` 里封装 DeepEval / EvalScope / 任意模型 API；定期 `record_human_label` 校准。
5. 在 CI 中调用 `scripts/agent-eval-gate.sh`，配置 `GateConfig` 阈值；每次改 prompt/模型/工具/拓扑必须过门禁。

## 目录

```
agent-eval/
├── agent_eval/            # 框架源码（五阶段模块）
├── datasets/golden/       # 示例评测集（JSONL）
├── examples/demo.py       # 端到端五阶段演示
└── tests/                 # 单元测试（unittest）
```
