# Agent Workflow 评测系统实现报告：agent-eval

> **调研主题**：Agent 评测（agent-eval）
> **调研日期**：2026-09-07
> **产物**：`agent-eval/` 参考实现 + `scripts/agent-eval-gate.sh` CI 门禁脚本

---

## 1. 背景与目标

前序调研结论：成熟的 agent 评测 = 公开 benchmark 定位能力上限 + 自建数据集离线回归 + 生产 tracing 在线评测；Better Harness 的精髓是"证据驱动 + 分级封顶 + 修复—验证分离"。

本次任务按五阶段计划落地一套可运行的 agent workflow 评测系统参考实现，验证该方法论可工程化。

## 2. 实现概览

代码位于 `agent-eval/`，纯 Python 标准库、零第三方依赖：

| 阶段 | 模块 | 关键能力 |
|------|------|----------|
| 1 观测地基 | `agent_eval/tracing.py` | OTel 风格 Trace/Span；记录节点输入输出、工具调用参数、模型调用 token/成本、错误重试、耗时；强制 `VersionTags`（prompt/模型/工具/拓扑四版本标签）；JSON 序列化可导入 Langfuse/Phoenix |
| 2 评审单元 | `agent_eval/episode.py` | `TaskEpisode` = 一个目标 + 一个验收边界；4 种确定性验收（assertion/exact_match/contains/structure）+ `Rubric` |
| 3 分层指标 | `agent_eval/metrics.py` | 结果层、轨迹层、步骤层、系统层指标函数；资产层 `AssetLedger`：Present(74)→Wired(84)→Exercised(94)→Outcome-supported(100) 四级证据封顶评分，`observe_trace` 依据真实调用自动推进证据 |
| 4 数据集与执行器 | `agent_eval/dataset.py`、`agent_eval/evaluators.py` | JSONL 黄金集（golden/synthetic/regression 三来源、失败案例回流）；确定性断言、参考轨迹匹配（4 种模式）、LLM-as-a-Judge 注入接口（含人工标注校准报告）、`EvalRunner` |
| 5 迭代闭环 | `agent_eval/gate.py`、`agent_eval/learning.py` | CI 门禁（阈值 + 基线对比 + 回归超限失败，仅通过者可固化基线）；`LearningLedger` 修复—验证分离状态机（proposed→applied→verified/regressed），只有后续窗口证明改善且守护集无回归才允许资产升 Outcome-supported |

## 3. 测试结果

| 测试场景 | 预期结果 | 实际结果 | 通过 |
|----------|----------|----------|------|
| 单元测试 `python -m unittest discover -s tests` | 全部通过 | 22/22 通过 | ✅ |
| 端到端 demo（4 条用例 × 3 评测器） | 全评测器 pass_rate=1.0 | 一致 | ✅ |
| 未使用资产封顶 | unused-skill 得分 ≤74 | 74（Present） | ✅ |
| 被行使工具评分 | calculator/search 升 Exercised | 94 | ✅ |
| 修复—验证分离 | applied 阶段不涨分；verify 后升 Outcome-supported | 一致（100） | ✅ |
| 门禁基线回归拦截 | 成功率下降超阈值 → 门禁失败且禁止存基线 | 一致 | ✅ |

运行方式：`bash scripts/agent-eval-gate.sh`（CI 中非零退出即阻断上线）。

## 4. 关键设计决策

1. **零依赖**：作为参考骨架，接口对齐主流工具语义（OTel span、agentevals 轨迹匹配模式、DeepEval judge 注入），生产落地时可逐模块替换为 Langfuse/Phoenix（观测）、DeepEval/EvalScope（judge）、agentevals（轨迹）。
2. **证据封顶而非计分公式**：`score = min(原始分, 证据上限)`，从机制上杜绝"配置即得分"。
3. **证据只升不降、修复不即时涨分**：`LearningLedger.verify` 是资产升 Outcome-supported 的唯一入口，且要求后续窗口 + guardrail 双重证据。
4. **失败案例回流**：`add_regression_case` 把线上失败追加为 regression 用例，配合 `LearningLedger.discover` 检测重复失败模式，形成"发现→沉淀→验证→再评分"飞轮。

## 5. 结论与建议

> **结论**：✅ 方法论可工程化，参考实现全部验收通过。

### 下一步行动

- [ ] 用真实 workflow 替换 demo 中的模拟 agent，接入真实 trace
- [ ] `LLMJudge.judge_fn` 封装真实模型 API，并开始人工标注校准
- [ ] 黄金集扩充到每类任务 20–50 条；接通生产失败回流
- [ ] 把 `scripts/agent-eval-gate.sh` 挂入 CI（prompt/模型/工具/拓扑变更必跑）
