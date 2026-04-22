#!/bin/bash
# Start Qwen2.5-14B-Instruct for RAG system
# Port 8080 (TEI uses 8003 for embeddings, so use different port for LLM)
# Full GPU offload with RTX 4070 (12GB VRAM, model ~9GB)

set -e

MODEL="/home/l/rag-dashboard/models/qwen2.5-7b-instruct-q4_k_m.gguf"
PORT=8080
CTX=32768
GPU_LAYERS=999  # full offload

NVIDIA_LIBS=$(python3 -c "
import os, glob
dirs = glob.glob('/home/l/rag-dashboard/venv/lib/python3.13/site-packages/nvidia/*/lib')
print(':'.join(dirs))
" 2>/dev/null)
export LD_LIBRARY_PATH="${NVIDIA_LIBS}:${LD_LIBRARY_PATH}"

echo "Starting Qwen2.5-14B-Instruct on port $PORT..."
echo "Model: $MODEL"
echo "GPU layers: $GPU_LAYERS (full offload)"
echo "Context: $CTX tokens"

exec /home/l/rag-dashboard/llama.cpp/build/bin/llama-server \
  -m "$MODEL" \
  --port "$PORT" \
  --host 127.0.0.1 \
  --ctx-size "$CTX" \
  --n-gpu-layers "$GPU_LAYERS" \
  --jinja \
  --parallel 2 \
  -n -1 \
  --flash-attn on
