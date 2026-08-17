#!/usr/bin/env bash
# evaluate.sh — 开源方案自动化评估入口脚本
#
# 用法：
#   bash scripts/evaluate.sh <方案名称> [报告主题]
#
# 示例：
#   bash scripts/evaluate.sh playwright ui-automation
#
# 约定：
#   - 每个方案对应 scripts/<方案名称>.sh（具体测试逻辑）
#   - 评估报告模板从 docs/templates/evaluation-template.md 复制生成
#   - 报告输出到 docs/reports/<报告主题>/<方案名称>.md

set -euo pipefail

SOLUTION="${1:-}"
TOPIC="${2:-general}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE="${REPO_ROOT}/docs/templates/evaluation-template.md"
REPORT_DIR="${REPO_ROOT}/docs/reports/${TOPIC}"
REPORT_FILE="${REPORT_DIR}/${SOLUTION}.md"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
usage() {
  echo "Usage: $0 <solution-name> [topic]"
  echo ""
  echo "  solution-name  Name of the open-source solution to evaluate"
  echo "  topic          Research topic folder (default: general)"
  exit 1
}

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
err()  { echo "[ERROR] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Validate input
# ---------------------------------------------------------------------------
[[ -z "${SOLUTION}" ]] && usage

# ---------------------------------------------------------------------------
# Create report scaffold if it doesn't already exist
# ---------------------------------------------------------------------------
if [[ ! -f "${REPORT_FILE}" ]]; then
  mkdir -p "${REPORT_DIR}"
  cp "${TEMPLATE}" "${REPORT_FILE}"
  # Replace placeholder {方案名称} with the actual solution name
  perl -i -pe "s/\{方案名称\}/${SOLUTION}/g" "${REPORT_FILE}"
  perl -i -pe "s/\{YYYY-MM-DD\}/$(date '+%Y-%m-%d')/g" "${REPORT_FILE}"
  log "Report scaffold created: ${REPORT_FILE}"
else
  log "Report already exists, skipping scaffold: ${REPORT_FILE}"
fi

# ---------------------------------------------------------------------------
# Run solution-specific test script (if available)
# ---------------------------------------------------------------------------
SOLUTION_SCRIPT="${SCRIPT_DIR}/${SOLUTION}.sh"
if [[ -f "${SOLUTION_SCRIPT}" ]]; then
  log "Running solution test script: ${SOLUTION_SCRIPT}"
  bash "${SOLUTION_SCRIPT}" 2>&1 | tee -a "${REPORT_DIR}/${SOLUTION}-test.log"
  log "Test script finished. Log: ${REPORT_DIR}/${SOLUTION}-test.log"
else
  log "No solution-specific script found at ${SOLUTION_SCRIPT}."
  log "Create ${SOLUTION_SCRIPT} to automate testing for '${SOLUTION}'."
fi

log "Evaluation workflow complete."
log "Next step: fill in the analysis report at ${REPORT_FILE}"
