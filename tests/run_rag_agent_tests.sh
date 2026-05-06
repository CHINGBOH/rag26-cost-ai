#!/bin/bash
# =============================================================================
# RAG Agent live regression runner
# =============================================================================
# 用法:
#   chmod +x tests/run_rag_agent_tests.sh
#   ./tests/run_rag_agent_tests.sh          # 运行全部测试
#   ./tests/run_rag_agent_tests.sh --node   # 仅运行Node SSE smoke
#   ./tests/run_rag_agent_tests.sh --python # 仅运行16题金标回归
#   ./tests/run_rag_agent_tests.sh --report # 仅生成报告（基于上次测试结果）
#
# 环境变量:
#   RAG_TEST_NODE_URL    - Node后端地址，默认 http://localhost:3001
#   RAG_TEST_PYTHON_URL  - Retrieval后端地址（兼容旧变量名），默认 http://localhost:8002
#   RAG_TEST_GATEWAY_URL - API网关地址，默认 http://localhost:8080
# =============================================================================

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 默认值
NODE_URL="${RAG_TEST_NODE_URL:-http://localhost:3001}"
PYTHON_URL="${RAG_TEST_PYTHON_URL:-${RAG_TEST_RETRIEVAL_URL:-http://localhost:8002}}"
GATEWAY_URL="${RAG_TEST_GATEWAY_URL:-http://localhost:8080}"
REPORT_DIR="${REPORT_DIR:-$(pwd)/tests/reports}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE="${REPORT_DIR}/rag_agent_test_report_${TIMESTAMP}.json"

# 项目路径
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NODE_TEST_DIR="${PROJECT_ROOT}/src/backend/server"
PYTHON_TEST_DIR="${PROJECT_ROOT}"

mkdir -p "${REPORT_DIR}"

# 参数解析
RUN_NODE=false
RUN_PYTHON=false
RUN_GATEWAY=false
GENERATE_REPORT_ONLY=false
VERBOSE=false

for arg in "$@"; do
  case $arg in
    --node) RUN_NODE=true ;;
    --python) RUN_PYTHON=true ;;
    --gateway) RUN_GATEWAY=true ;;
    --report) GENERATE_REPORT_ONLY=true ;;
    -v|--verbose) VERBOSE=true ;;
    -h|--help)
      echo "用法: $0 [选项]"
      echo "选项:"
      echo "  --node      仅运行Node端测试"
      echo "  --python    仅运行Python端测试"
      echo "  --gateway   仅运行网关测试"
      echo "  --report    仅生成报告"
      echo "  -v, --verbose  详细输出"
      echo "  -h, --help  显示此帮助"
      exit 0
      ;;
  esac
done

# 默认全部运行
if [[ "$RUN_NODE" == "false" && "$RUN_PYTHON" == "false" && "$RUN_GATEWAY" == "false" && "$GENERATE_REPORT_ONLY" == "false" ]]; then
  RUN_NODE=true
  RUN_PYTHON=true
  RUN_GATEWAY=true
fi

# =============================================================================
# 辅助函数
# =============================================================================

log_info() {
  echo -e "${BLUE}[INFO]${NC} $1"
}

log_warn() {
  echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $1"
}

log_success() {
  echo -e "${GREEN}[PASS]${NC} $1"
}

check_service() {
  local url=$1
  local name=$2
  if curl -sf "${url}/health" > /dev/null 2>&1; then
    log_success "${name} 可用 (${url})"
    return 0
  else
    log_warn "${name} 不可用 (${url})"
    return 1
  fi
}

# =============================================================================
# 服务健康检查
# =============================================================================

echo "========================================"
echo "  RAG Agent live regression"
echo "========================================"
echo ""

log_info "检查服务健康状态..."
NODE_HEALTHY=false
PYTHON_HEALTHY=false
GATEWAY_HEALTHY=false

check_service "$NODE_URL" "Node后端" && NODE_HEALTHY=true
check_service "$PYTHON_URL" "Python后端" && PYTHON_HEALTHY=true
check_service "$GATEWAY_URL" "API网关" && GATEWAY_HEALTHY=true

echo ""

# =============================================================================
# 运行测试
# =============================================================================

NODE_RESULTS="{}"
PYTHON_RESULTS="{}"
GATEWAY_RESULTS="{}"
NODE_REPORT_FILE=""
PYTHON_REPORT_FILE=""
GATEWAY_REPORT_FILE=""

# ---------- Node端测试 ----------
if [[ "$RUN_NODE" == "true" && "$GENERATE_REPORT_ONLY" == "false" ]]; then
  log_info "运行Node端测试 (Vitest)..."
  cd "$NODE_TEST_DIR"

  if [[ "$NODE_HEALTHY" == "false" ]]; then
    log_warn "Node服务不可用，Node测试将跳过大部分用例"
  fi

  # 安装依赖（如果需要）
  if [[ ! -d "node_modules" ]]; then
    log_info "安装Node依赖..."
    npm install
  fi

  NODE_REPORT_FILE="${REPORT_DIR}/node_test_${TIMESTAMP}.json"

  if RAG_RUN_LIVE_AGENT_TESTS=1 \
     RAG_TEST_NODE_URL="${NODE_URL}" \
     RAG_TEST_RETRIEVAL_URL="${PYTHON_URL}" \
     npx vitest run src/__tests__/rag-agent-core.test.ts --reporter=json --outputFile="${NODE_REPORT_FILE}" 2>/dev/null; then
    log_success "Node端测试执行完成"
    if [[ -f "$NODE_REPORT_FILE" ]]; then
      NODE_RESULTS=$(cat "$NODE_REPORT_FILE")
    fi
  else
    log_error "Node端测试执行失败或部分失败"
    if [[ -f "$NODE_REPORT_FILE" ]]; then
      NODE_RESULTS=$(cat "$NODE_REPORT_FILE")
    fi
  fi
  echo ""
fi

# ---------- 16题金标回归 ----------
if [[ "$RUN_PYTHON" == "true" && "$GENERATE_REPORT_ONLY" == "false" ]]; then
  log_info "运行16题金标回归 (tests/test_agent_16.py)..."
  cd "$PYTHON_TEST_DIR"

  if [[ "$PYTHON_HEALTHY" == "false" ]]; then
    log_warn "Retrieval服务不可用，16题金标回归可能失败"
  fi

  PYTHON_REPORT_FILE="${REPORT_DIR}/python_test_${TIMESTAMP}.json"
  CANONICAL_RESULTS_FILE="${PROJECT_ROOT}/logs/agent_test_16_results.json"

  if python tests/test_agent_16.py; then
    log_success "16题金标回归执行完成"
  else
    log_error "16题金标回归执行失败或部分失败"
  fi

  if [[ -f "$CANONICAL_RESULTS_FILE" ]]; then
    cp "$CANONICAL_RESULTS_FILE" "$PYTHON_REPORT_FILE"
    PYTHON_RESULTS=$(cat "$PYTHON_REPORT_FILE")
  fi
  echo ""
fi

# ---------- 网关测试 ----------
if [[ "$RUN_GATEWAY" == "true" && "$GENERATE_REPORT_ONLY" == "false" ]]; then
  log_info "运行网关连通性测试..."

  GATEWAY_REPORT_FILE="${REPORT_DIR}/gateway_test_${TIMESTAMP}.json"
  GATEWAY_PASSED=0
  GATEWAY_FAILED=0
  GATEWAY_DETAILS="[]"

  # 简单的curl测试
  if curl -sf "${GATEWAY_URL}/health" > /dev/null 2>&1; then
    GATEWAY_PASSED=$((GATEWAY_PASSED + 1))
    GATEWAY_DETAILS=$(echo "$GATEWAY_DETAILS" | sed 's/\[\]/[{"test": "health", "passed": true}]/' || echo "$GATEWAY_DETAILS")
  else
    GATEWAY_FAILED=$((GATEWAY_FAILED + 1))
    GATEWAY_DETAILS=$(echo "$GATEWAY_DETAILS" | sed 's/\[\]/[{"test": "health", "passed": false}]/' || echo "$GATEWAY_DETAILS")
  fi

  GATEWAY_RESULTS=$(cat <<EOF
{
  "passed": $GATEWAY_PASSED,
  "failed": $GATEWAY_FAILED,
  "details": $GATEWAY_DETAILS
}
EOF
)
  echo "$GATEWAY_RESULTS" > "$GATEWAY_REPORT_FILE"
  echo ""
fi

# =============================================================================
# 生成综合报告
# =============================================================================

log_info "生成综合测试报告: ${REPORT_FILE}"

python3 - <<PYEOF
import json
import os
import sys
from datetime import datetime

report = {
    "meta": {
        "timestamp": datetime.now().isoformat(),
        "node_url": os.environ.get("RAG_TEST_NODE_URL", "http://localhost:3001"),
        "python_url": os.environ.get("RAG_TEST_PYTHON_URL", os.environ.get("RAG_TEST_RETRIEVAL_URL", "http://localhost:8002")),
        "gateway_url": os.environ.get("RAG_TEST_GATEWAY_URL", "http://localhost:8080"),
    },
    "health": {
        "node": ${NODE_HEALTHY@Q},
        "python": ${PYTHON_HEALTHY@Q},
        "gateway": ${GATEWAY_HEALTHY@Q},
    },
    "summary": {
        "total": 16,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
    },
    "details": [],
    "node_results": {},
    "python_results": {},
    "gateway_results": {},
}

# 尝试解析Node报告
node_report_path = "${NODE_REPORT_FILE}"
if node_report_path and os.path.exists(node_report_path):
    try:
        with open(node_report_path, "r", encoding="utf-8") as f:
            node_data = json.load(f)
        report["node_results"] = {
            "testFiles": node_data.get("testFiles", 0),
            "numPassedTests": node_data.get("numPassedTests", 0),
            "numFailedTests": node_data.get("numFailedTests", 0),
            "numSkippedTests": node_data.get("numSkippedTests", 0),
        }
        report["summary"]["passed"] += node_data.get("numPassedTests", 0)
        report["summary"]["failed"] += node_data.get("numFailedTests", 0)
        report["summary"]["skipped"] += node_data.get("numSkippedTests", 0)
    except Exception as e:
        report["node_results"] = {"error": str(e)}

# 尝试解析Python报告
python_report_path = "${PYTHON_REPORT_FILE}"
if python_report_path and os.path.exists(python_report_path):
    try:
        with open(python_report_path, "r", encoding="utf-8") as f:
            py_data = json.load(f)
        total = py_data.get("summary", {}).get("total", 0)
        passed = py_data.get("summary", {}).get("passed", 0)
        failed = max(total - passed, 0)
        report["python_results"] = {
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": py_data.get("summary", {}).get("errors", 0),
        }
        report["summary"]["passed"] += passed
        report["summary"]["failed"] += failed
    except Exception as e:
        report["python_results"] = {"error": str(e)}

# 尝试解析网关报告
gateway_report_path = "${GATEWAY_REPORT_FILE}"
if gateway_report_path and os.path.exists(gateway_report_path):
    try:
        with open(gateway_report_path, "r", encoding="utf-8") as f:
            gw_data = json.load(f)
        report["gateway_results"] = gw_data
    except Exception as e:
        report["gateway_results"] = {"error": str(e)}

with open("${REPORT_FILE}", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(json.dumps(report, ensure_ascii=False, indent=2))
PYEOF

echo ""
echo "========================================"
echo "  测试完成"
echo "  报告路径: ${REPORT_FILE}"
echo "========================================"

# 返回码：只要Node或Python有失败就返回1
if [[ -f "$NODE_REPORT_FILE" ]]; then
  NODE_FAILED=$(python3 -c "import json; d=json.load(open('$NODE_REPORT_FILE')); print(d.get('numFailedTests', 0))" 2>/dev/null || echo 0)
  if [[ "$NODE_FAILED" -gt 0 ]]; then
    exit 1
  fi
fi

if [[ -f "$PYTHON_REPORT_FILE" ]]; then
  PYTHON_FAILED=$(python3 -c "import json; d=json.load(open('$PYTHON_REPORT_FILE')); s=d.get('summary',{}); print(max(s.get('total',0)-s.get('passed',0), 0))" 2>/dev/null || echo 0)
  if [[ "$PYTHON_FAILED" -gt 0 ]]; then
    exit 1
  fi
fi

exit 0
