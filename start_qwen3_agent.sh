#!/usr/bin/env bash
# Qwen3-8B Agent Server
# --reasoning auto: 自动决定是否思考（工具调用前会思考，加精度）
# --reasoning-budget 2048: 限制思考 token，防止思考过长
# --jinja: 使用 jinja 模板（Qwen3 工具调用需要）
# --parallel 4: 允许 4 路并发（批量工具调用）
# -n -1: 无限生成长度

set -euo pipefail

MODEL_PATH="/home/l/rag-dashboard/models/qwen3-8b-q4_k_m.gguf"
LOG_DIR="/home/l/rag-dashboard/logs"
mkdir -p "$LOG_DIR"

if [ ! -f "$MODEL_PATH" ]; then
    echo "ERROR: Model not found at $MODEL_PATH"
    exit 1
fi

/home/l/rag-dashboard/llama.cpp/build/bin/llama-server \
  -m "$MODEL_PATH" \
  --port 8003 \
  --host 127.0.0.1 \
  --ctx-size 32768 \
  --n-gpu-layers 0 \
  --reasoning auto \
  --reasoning-budget 2048 \
  --jinja \
  --parallel 4 \
  -n -1 \
  2>&1 | tee "$LOG_DIR/qwen3-agent.log"
