#!/usr/bin/env bash
# agent-eval CI 门禁入口脚本（阶段5）
#
# 用法：
#   bash scripts/agent-eval-gate.sh          # 跑单元测试 + demo 门禁
#   bash scripts/agent-eval-gate.sh test     # 只跑单元测试
#   bash scripts/agent-eval-gate.sh demo     # 只跑端到端 demo（含门禁，失败时非零退出）
#
# 在 CI 中：每次改动 prompt/模型/工具/拓扑后运行本脚本，非零退出即阻断上线。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/agent-eval"

MODE="${1:-all}"

run_tests() {
  echo "==> 运行 agent_eval 单元测试"
  python -m unittest discover -s tests -v
}

run_demo() {
  echo "==> 运行端到端 demo（含 CI 门禁检查）"
  python examples/demo.py
}

case "$MODE" in
  test) run_tests ;;
  demo) run_demo ;;
  all)  run_tests && run_demo ;;
  *) echo "未知模式: $MODE（可选 test|demo|all）" >&2; exit 2 ;;
esac

echo "==> agent-eval 门禁通过"
