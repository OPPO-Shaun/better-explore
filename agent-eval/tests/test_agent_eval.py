"""agent_eval 单元测试（unittest，零依赖）。

运行::

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_eval import (
    AssetLedger,
    DeterministicEvaluator,
    EvalRunner,
    EvidenceLevel,
    Gate,
    GateConfig,
    GoldenCase,
    Intervention,
    LearningLedger,
    LLMJudge,
    TaskEpisode,
    Tracer,
    TrajectoryEvaluator,
    VersionTags,
    load_golden_set,
    outcome_metrics,
    save_golden_set,
    step_metrics,
    system_metrics,
    trajectory_metrics,
)
from agent_eval.episode import AcceptanceCriterion
from agent_eval.metrics import SCORE_CEILING

TAGS = VersionTags("p1", "m1", "t1", "w1")


def make_episode(succeed: bool = True, task_type: str = "qa",
                 tools: list[str] = ("calculator",),
                 ref: list[str] = ("calculator",)) -> TaskEpisode:
    tracer = Tracer(task_id="t", version_tags=TAGS)
    for tool in tools:
        tracer.record_tool_call(tool, args={"x": 1}, result="ok")
    tracer.record_llm_call("m1", input_tokens=10, output_tokens=5,
                           cost_usd=0.001)
    trace = tracer.finish()
    ep = TaskEpisode(
        episode_id="e1", goal="g", task_type=task_type,
        acceptance=[AcceptanceCriterion("c1", "", kind="contains",
                                        expected="42")],
        reference_trajectory=list(ref),
        final_output="答案是 42" if succeed else "不知道",
    )
    ep.add_trace(trace)
    return ep


class TestTracing(unittest.TestCase):
    def test_span_and_costs(self):
        tracer = Tracer("t1", TAGS)
        with tracer.span("plan", inputs="goal") as sp:
            sp.outputs = "plan"
        tracer.record_tool_call("search", args={"q": "x"}, result=[1])
        tracer.record_llm_call("m", input_tokens=100, output_tokens=20,
                               cost_usd=0.002)
        trace = tracer.finish()
        self.assertEqual(len(trace.spans), 3)
        self.assertEqual(trace.total_tokens, 120)
        self.assertAlmostEqual(trace.total_cost_usd, 0.002)
        self.assertEqual(len(trace.tool_calls()), 1)
        self.assertEqual(trace.version_tags.prompt_version, "p1")

    def test_span_captures_error(self):
        tracer = Tracer("t1", TAGS)
        with self.assertRaises(ValueError):
            with tracer.span("boom"):
                raise ValueError("bad")
        trace = tracer.finish()
        self.assertEqual(len(trace.errors()), 1)
        self.assertIn("ValueError", trace.errors()[0].error)

    def test_roundtrip_json(self):
        tracer = Tracer("t1", TAGS)
        tracer.record_tool_call("search", args={"q": "x"})
        trace = tracer.finish()
        import json
        restored = type(trace).from_dict(json.loads(trace.to_json()))
        self.assertEqual(restored.trace_id, trace.trace_id)
        self.assertEqual(restored.spans[0].tool_name, "search")


class TestEpisode(unittest.TestCase):
    def test_acceptance_kinds(self):
        trace = Tracer("t", TAGS).finish()
        cases = [
            ("exact_match", "42", "42", True),
            ("contains", "4", "42", True),
            ("contains", "9", "42", False),
            ("structure", ["a"], {"a": 1}, True),
            ("structure", ["a", "b"], {"a": 1}, False),
        ]
        for kind, expected, output, want in cases:
            c = AcceptanceCriterion("c", "", kind=kind, expected=expected)
            self.assertEqual(c.evaluate(trace, output), want, msg=kind)

    def test_assertion_criterion(self):
        c = AcceptanceCriterion(
            "c", "", kind="assertion",
            check=lambda trace, out: len(trace.tool_calls()) > 0)
        ep = make_episode()
        self.assertTrue(c.evaluate(ep.trace, ep.final_output))

    def test_succeeded(self):
        self.assertTrue(make_episode(True).succeeded)
        self.assertFalse(make_episode(False).succeeded)


class TestMetrics(unittest.TestCase):
    def test_outcome(self):
        eps = [make_episode(True), make_episode(False)]
        m = outcome_metrics(eps, satisfaction={"e1": 0.8})
        self.assertAlmostEqual(m["task_success_rate"], 0.5)
        self.assertEqual(m["n_episodes"], 2)

    def test_trajectory(self):
        ep = make_episode(tools=["calculator", "extra"], ref=["calculator"])
        m = trajectory_metrics(ep)
        self.assertEqual(m["step_deviation"], 1)
        self.assertEqual(m["plan_adherence"], 1.0)

    def test_step(self):
        ep = make_episode(tools=["calculator", "hammer"])
        m = step_metrics(ep, expected_tools=["calculator"],
                         arg_validator=lambda name, args: "x" in (args or {}))
        self.assertAlmostEqual(m["tool_selection_accuracy"], 0.5)
        self.assertAlmostEqual(m["arg_validity_rate"], 1.0)

    def test_system(self):
        m = system_metrics([make_episode(True), make_episode(False)])
        self.assertAlmostEqual(m["failure_rate"], 0.5)
        self.assertGreater(m["avg_tokens"], 0)


class TestAssetLedger(unittest.TestCase):
    def test_evidence_ceiling(self):
        ledger = AssetLedger()
        rec = ledger.register("skill-a", "skill", raw_score=100)
        # 只配置不使用 → Present 封顶 74
        self.assertEqual(rec.score, SCORE_CEILING[EvidenceLevel.PRESENT])
        ledger.mark("skill-a", EvidenceLevel.WIRED)
        self.assertEqual(rec.score, 84)
        # 证据只升不降
        ledger.mark("skill-a", EvidenceLevel.PRESENT)
        self.assertEqual(rec.evidence, EvidenceLevel.WIRED)

    def test_observe_trace_promotes_to_exercised(self):
        ledger = AssetLedger()
        ledger.register("calculator", "tool")
        ep = make_episode()
        ledger.observe_trace(ep.trace)
        self.assertEqual(ledger.get("calculator").evidence,
                         EvidenceLevel.EXERCISED)
        self.assertEqual(ledger.get("calculator").score, 94)


class TestDatasetAndEvaluators(unittest.TestCase):
    def _case(self, **kw) -> GoldenCase:
        base = dict(
            case_id="c1", task_type="qa", goal="g",
            acceptance=[{"criterion_id": "a1", "kind": "contains",
                         "expected": "42"}],
            reference_trajectory=["calculator"],
        )
        base.update(kw)
        return GoldenCase(**base)

    def test_dataset_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "set.jsonl"
            save_golden_set([self._case(), self._case(case_id="c2",
                                                      source="regression")], p)
            loaded = load_golden_set(p)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[1].source, "regression")

    def test_invalid_source_rejected(self):
        with self.assertRaises(ValueError):
            self._case(source="bogus")

    def test_deterministic_evaluator(self):
        r = DeterministicEvaluator().evaluate(self._case(), make_episode(True))
        self.assertTrue(r.passed)
        r = DeterministicEvaluator().evaluate(self._case(), make_episode(False))
        self.assertFalse(r.passed)

    def test_trajectory_modes(self):
        ep = make_episode(tools=["calculator", "extra"])
        case = self._case()
        self.assertTrue(TrajectoryEvaluator("superset").evaluate(case, ep).passed)
        self.assertFalse(TrajectoryEvaluator("subset").evaluate(case, ep).passed)
        self.assertFalse(TrajectoryEvaluator("strict").evaluate(case, ep).passed)

    def test_llm_judge_and_calibration(self):
        judge = LLMJudge(lambda c, e: (0.9, "good"), pass_threshold=0.7)
        r = judge.evaluate(self._case(), make_episode())
        self.assertTrue(r.passed)
        judge.record_human_label("c1", 0.8)
        rep = judge.calibration_report()
        self.assertEqual(rep["n_labeled"], 1)
        self.assertAlmostEqual(rep["mean_abs_error"], 0.1, places=5)

    def test_runner(self):
        runner = EvalRunner([DeterministicEvaluator()])
        out = runner.run([self._case()], lambda c: make_episode(True))
        self.assertEqual(out["summary"]["deterministic"]["pass_rate"], 1.0)


class TestGate(unittest.TestCase):
    def test_gate_pass_fail_and_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            gate = Gate(GateConfig(min_task_success_rate=0.9,
                                   min_criteria_pass_rate=0.9),
                        baseline_path=Path(d) / "baseline.json")
            good = [make_episode(True) for _ in range(5)]
            rep = gate.check(good, TAGS)
            self.assertTrue(rep.passed)
            gate.save_baseline(rep)
            # 大幅回归后：阈值失败 + 相对基线回归失败
            bad = [make_episode(True), make_episode(False)]
            rep2 = gate.check(bad, TAGS)
            self.assertFalse(rep2.passed)
            self.assertFalse(rep2.checks["no_success_regression"])
            with self.assertRaises(ValueError):
                gate.save_baseline(rep2)


class TestLearningLedger(unittest.TestCase):
    def test_repair_verify_separation(self):
        assets = AssetLedger()
        assets.register("search", "tool")
        ledger = LearningLedger(asset_ledger=assets)
        ledger.propose(Intervention("iv1", "fix", target_asset_id="search"))
        ledger.apply("iv1", baseline_episodes=[make_episode(False)])
        # applied 阶段不允许资产涨到 Outcome-supported
        self.assertNotEqual(assets.get("search").evidence,
                            EvidenceLevel.OUTCOME_SUPPORTED)
        ledger.verify("iv1", later_episodes=[make_episode(True)],
                      guardrail_episodes=[make_episode(True)])
        self.assertEqual(ledger.get("iv1").status, "verified")
        self.assertEqual(assets.get("search").evidence,
                         EvidenceLevel.OUTCOME_SUPPORTED)

    def test_regression_blocks_verification(self):
        assets = AssetLedger()
        assets.register("search", "tool")
        ledger = LearningLedger(asset_ledger=assets)
        ledger.propose(Intervention("iv1", "fix", target_asset_id="search"))
        ledger.apply("iv1", baseline_episodes=[make_episode(True)])
        ledger.verify("iv1", later_episodes=[make_episode(False)])
        self.assertEqual(ledger.get("iv1").status, "regressed")
        self.assertNotEqual(assets.get("search").evidence,
                            EvidenceLevel.OUTCOME_SUPPORTED)

    def test_discover_repeated_failures(self):
        ledger = LearningLedger()
        fails = [make_episode(False, task_type="search") for _ in range(3)]
        self.assertEqual(ledger.discover(fails), ["search"])


if __name__ == "__main__":
    unittest.main()
