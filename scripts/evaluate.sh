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
# 工具函数
# ---------------------------------------------------------------------------
usage() {
  echo "用法：$0 <方案名称> [报告主题]"
  echo ""
  echo "  方案名称    待评估的开源方案名称"
  echo "  报告主题    报告归档目录（默认：general）"
  exit 1
}

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
err()  { echo "[错误] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------
[[ -z "${SOLUTION}" ]] && usage

# ---------------------------------------------------------------------------
# 如果报告不存在，则从模板创建报告骨架
# ---------------------------------------------------------------------------
if [[ ! -f "${REPORT_FILE}" ]]; then
  mkdir -p "${REPORT_DIR}"
  cp "${TEMPLATE}" "${REPORT_FILE}"
  # 将模板占位符替换为实际方案名称和日期
  perl -i -pe "s/\{方案名称\}/${SOLUTION}/g" "${REPORT_FILE}"
  perl -i -pe "s/\{YYYY-MM-DD\}/$(date '+%Y-%m-%d')/g" "${REPORT_FILE}"
  log "报告骨架已创建：${REPORT_FILE}"
else
  log "报告已存在，跳过创建：${REPORT_FILE}"
fi

# ---------------------------------------------------------------------------
# 执行方案专属测试脚本（如果存在）
# ---------------------------------------------------------------------------
SOLUTION_SCRIPT="${SCRIPT_DIR}/${SOLUTION}.sh"
if [[ -f "${SOLUTION_SCRIPT}" ]]; then
  log "正在执行方案测试脚本：${SOLUTION_SCRIPT}"
  bash "${SOLUTION_SCRIPT}" 2>&1 | tee -a "${REPORT_DIR}/${SOLUTION}-test.log"
  log "测试脚本执行完毕。日志：${REPORT_DIR}/${SOLUTION}-test.log"
else
  log "未找到方案专属脚本：${SOLUTION_SCRIPT}"
  log "可创建 ${SOLUTION_SCRIPT} 以自动化测试「${SOLUTION}」方案。"
fi

log "评估流程完成。"
log "下一步：补充分析报告 ${REPORT_FILE}"

