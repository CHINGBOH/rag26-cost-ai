#!/bin/bash
# Start Qwen2.5-14B-Instruct via llama.cpp server (port 8888)
# Qwen2.5-14B has 48 transformer layers; Q4_K_M ≈ 8.1GB
# RTX 4070 12GB: try full GPU first, fallback to partial offload

set -e

MODEL_SHARD1="/home/l/rag-dashboard/models/qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf"
LLAMA_SERVER="/home/l/rag-dashboard/llama.cpp/build/bin/llama-server"
PORT=8888
CTX=8192    # 8k context; keeps VRAM under 12GB on RTX 4070

# Detect free VRAM and pick GPU layers accordingly
FREE_VRAM_MB=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 || echo 0)
if [ "$FREE_VRAM_MB" -ge 9000 ]; then
    GPU_LAYERS=999   # full offload
elif [ "$FREE_VRAM_MB" -ge 7500 ]; then
    GPU_LAYERS=42
elif [ "$FREE_VRAM_MB" -ge 6000 ]; then
    GPU_LAYERS=36
else
    GPU_LAYERS=28    # heavy CPU offload
fi

echo "Free VRAM: ${FREE_VRAM_MB}MB → GPU layers: ${GPU_LAYERS}"
echo "Starting Qwen2.5-14B-Instruct on port $PORT (ctx=$CTX)..."

# Need NVIDIA libs from venv for CUDA support
NVIDIA_LIBS=$(python3 -c "
import glob
dirs = glob.glob('/home/l/rag-dashboard/venv/lib/python*/site-packages/nvidia/*/lib')
print(':'.join(dirs))
" 2>/dev/null)
[ -n "$NVIDIA_LIBS" ] && export LD_LIBRARY_PATH="${NVIDIA_LIBS}:${LD_LIBRARY_PATH}"

exec "$LLAMA_SERVER" \
    -m "$MODEL_SHARD1" \
    --port "$PORT" \
    --host 127.0.0.1 \
    --ctx-size "$CTX" \
    --n-gpu-layers "$GPU_LAYERS" \
    --cache-type-k q4_0 \
    --cache-type-v q4_0 \
    --flash-attn on \
    --parallel 1 \
    -n -1 \
    --jinja
