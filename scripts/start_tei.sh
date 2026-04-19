#!/bin/bash
# =============================================================================
# TEI (Text Embeddings Inference) 启动脚本
# =============================================================================
# 用于启动 HuggingFace TEI 高性能 Embedding 服务
# 支持 GPU 加速，使用 BAAI/bge-m3 模型
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 配置
TEI_IMAGE="ghcr.io/huggingface/text-embeddings-inference:1.5"
TEI_PORT="${TEI_PORT:-8003}"
TEI_MODEL_ID="${TEI_MODEL_ID:-BAAI/bge-m3}"
TEI_MAX_BATCH_TOKENS="${TEI_MAX_BATCH_TOKENS:-16384}"
TEI_MAX_CLIENT_BATCH_SIZE="${TEI_MAX_CLIENT_BATCH_SIZE:-64}"
MODELS_DIR="${PROJECT_ROOT}/models"

echo "============================================================================="
echo "  TEI (Text Embeddings Inference) 启动脚本"
echo "============================================================================="
echo ""
echo "  镜像: ${TEI_IMAGE}"
echo "  端口: ${TEI_PORT}"
echo "  模型: ${TEI_MODEL_ID}"
echo "  模型目录: ${MODELS_DIR}"
echo ""

# 检查 Docker
echo "[1/4] 检查 Docker 环境..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "❌ Docker 守护进程未运行，请启动 Docker"
    exit 1
fi
echo "✅ Docker 环境正常"

# 检查 NVIDIA Docker 运行时 (GPU 支持)
echo ""
echo "[2/4] 检查 GPU 支持..."
if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null; then
    echo "✅ 检测到 NVIDIA GPU，启用 GPU 加速"
    GPU_ARGS="--gpus all"
else
    echo "⚠️ 未检测到 NVIDIA GPU，使用 CPU 模式 (性能较低)"
    GPU_ARGS=""
fi

# 拉取镜像
echo ""
echo "[3/4] 检查/拉取 TEI 镜像..."
if docker inspect "${TEI_IMAGE}" &> /dev/null; then
    echo "✅ 镜像 ${TEI_IMAGE} 已存在"
else
    echo "⬇️  正在拉取镜像 ${TEI_IMAGE} (这可能需要几分钟)..."
    docker pull "${TEI_IMAGE}"
    echo "✅ 镜像拉取完成"
fi

# 停止并删除旧容器
echo ""
echo "[4/4] 启动 TEI 容器..."
if docker ps -a --format '{{.Names}}' | grep -q "^rag-tei$"; then
    echo "🛑 停止并移除旧的 rag-tei 容器..."
    docker stop rag-tei &> /dev/null || true
    docker rm rag-tei &> /dev/null || true
fi

# 确保模型目录存在
mkdir -p "${MODELS_DIR}"

# 启动容器
echo "🚀 启动 TEI 容器 (端口: ${TEI_PORT})..."
docker run -d \
    --name rag-tei \
    -p "${TEI_PORT}:80" \
    -v "${MODELS_DIR}:/data" \
    ${GPU_ARGS} \
    -e "MODEL_ID=${TEI_MODEL_ID}" \
    -e "PORT=80" \
    -e "MAX_BATCH_TOKENS=${TEI_MAX_BATCH_TOKENS}" \
    -e "MAX_CLIENT_BATCH_SIZE=${TEI_MAX_CLIENT_BATCH_SIZE}" \
    --health-cmd="curl -f http://localhost:80/health || exit 1" \
    --health-interval=30s \
    --health-timeout=10s \
    --health-retries=5 \
    --health-start-period=60s \
    --restart unless-stopped \
    "${TEI_IMAGE}" \
    --model-id "${TEI_MODEL_ID}" \
    --revision main \
    --port 80 \
    --max-batch-tokens "${TEI_MAX_BATCH_TOKENS}" \
    --max-client-batch-size "${TEI_MAX_CLIENT_BATCH_SIZE}"

echo ""
echo "✅ TEI 容器已启动!"
echo ""
echo "============================================================================="
echo "  服务信息"
echo "============================================================================="
echo "  HTTP 端点: http://localhost:${TEI_PORT}"
echo "  Health:   http://localhost:${TEI_PORT}/health"
echo "  Embed:    POST http://localhost:${TEI_PORT}/embed"
echo "  模型:     ${TEI_MODEL_ID}"
echo ""
echo "  查看日志: docker logs -f rag-tei"
echo "  停止服务: docker stop rag-tei"
echo "  移除容器: docker rm rag-tei"
echo ""
echo "  Python 后端配置:"
echo "    EMBEDDING_BACKEND=tei"
echo "    TEI_URL=http://localhost:${TEI_PORT}"
echo "============================================================================="
echo ""

# 等待服务就绪
echo "⏳ 等待 TEI 服务就绪 (最多 120 秒)..."
for i in {1..120}; do
    if curl -sf "http://localhost:${TEI_PORT}/health" &> /dev/null; then
        echo ""
        echo "✅ TEI 服务已就绪!"
        echo ""
        # 显示模型信息
        curl -s "http://localhost:${TEI_PORT}/info" 2>/dev/null | python3 -m json.tool 2>/dev/null || true
        exit 0
    fi
    echo -n "."
    sleep 1
done

echo ""
echo "⚠️  等待超时，服务可能仍在启动中。请查看日志: docker logs -f rag-tei"
exit 1
