#!/bin/bash
set -e

echo "======================================"
echo "PaddleOCR FastAPI Service Starting..."
echo "======================================"

# 验证 Paddle 环境
python -c "import paddle; print('Paddle version:', paddle.__version__); print('CUDA compiled:', paddle.is_compiled_with_cuda())"

# 启动 uvicorn
# --workers 1 是因为 PaddleOCR 内部已经用了多线程/多进程，
# uvicorn 多 worker 会重复加载模型，吃更多内存。
exec python -m uvicorn ocr_service:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8001}" \
    --workers 1 \
    --timeout-keep-alive 300
