#!/bin/bash
# RAG Dashboard 全系统启动脚本

set -e

echo "
╔═══════════════════════════════════════════════════════════╗
║     RAG Dashboard 全系统启动                              ║
╚═══════════════════════════════════════════════════════════╝
"

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 1. 检查基础设施
echo -e "${BLUE}[1/4] 检查基础设施...${NC}"

# 检查 Docker 服务
if ! sudo docker ps | grep -q "qdrant\|elasticsearch\|neo4j\|redis"; then
    echo "⚠️  基础设施未运行，正在启动..."
    # 这里可以添加启动 docker 的命令
else
    echo "✅ 基础设施已运行"
fi

# 2. 启动 OCR 服务
echo -e "${BLUE}[2/4] 启动 OCR 服务...${NC}"
OCR_PID=$(pgrep -f "uvicorn ocr_service" || true)
if [ -z "$OCR_PID" ]; then
    cd /home/l/rag-dashboard/src/backend/ocr-service
    source /home/l/miniconda3/etc/profile.d/conda.sh
    conda activate paddleocr
    nohup python -m uvicorn ocr_service:app --host 0.0.0.0 --port 8001 > /tmp/ocr_service.log 2>&1 &
    echo "✅ OCR 服务已启动 (端口 8001)"
else
    echo "✅ OCR 服务已在运行 (PID: $OCR_PID)"
fi

# 3. 启动主后端服务
echo -e "${BLUE}[3/4] 启动主后端服务...${NC}"
BACKEND_PID=$(pgrep -f "uvicorn main:app" || true)
if [ -z "$BACKEND_PID" ]; then
    cd /home/l/rag-dashboard/src/backend/python-legacy
    source /home/l/rag-dashboard/venv/bin/activate
    nohup python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload > /tmp/backend.log 2>&1 &
    sleep 3
    echo "✅ 主后端服务已启动 (端口 8000)"
else
    echo "✅ 主后端服务已在运行 (PID: $BACKEND_PID)"
fi

# 4. 启动前端
echo -e "${BLUE}[4/4] 启动前端...${NC}"
cd /home/l/rag-dashboard/src/frontend/web
FRONTEND_PID=$(pgrep -f "vite" || true)
if [ -z "$FRONTEND_PID" ]; then
    nohup npm run dev > /tmp/frontend.log 2>&1 &
    echo "✅ 前端已启动 (端口 3000)"
else
    echo "✅ 前端已在运行 (PID: $FRONTEND_PID)"
fi

echo "
╔═══════════════════════════════════════════════════════════╗
║     所有服务已启动！                                       ║
║                                                           ║
║     前端:    http://localhost:3000                        ║
║     后端:    http://localhost:8000                        ║
║     API文档: http://localhost:8000/docs                   ║
║     OCR:     http://localhost:8001                        ║
║                                                           ║
║     健康检查: curl http://localhost:8000/health           ║
╚═══════════════════════════════════════════════════════════╝
"

# 显示状态
echo "服务状态:"
sleep 2
curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "健康检查失败"
