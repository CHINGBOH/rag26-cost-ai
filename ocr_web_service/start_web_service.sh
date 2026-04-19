#!/bin/bash

# OCR Web服务启动脚本
# 一键启动前端UI和后端API服务

set -e

echo "========================================"
echo "OCR Web服务启动"
echo "========================================"
echo ""

# 配置
OCR_SERVICE_PORT=8001
WEB_SERVICE_PORT=8002
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# 检查OCR服务
check_ocr_service() {
    print_info "检查OCR服务..."
    
    if curl -s "http://localhost:${OCR_SERVICE_PORT}/health" > /dev/null 2>&1; then
        print_success "OCR服务已运行"
        return 0
    else
        print_warning "OCR服务未运行，正在启动..."
        
        # 检查OCR容器
        if docker ps | grep -q "ocr-gpu"; then
            docker restart ocr-gpu
        else
            docker run -d -p "${OCR_SERVICE_PORT}:8001" --name ocr-gpu ocr-service:gpu
        fi
        
        # 等待服务启动
        for i in {1..30}; do
            if curl -s "http://localhost:${OCR_SERVICE_PORT}/health" > /dev/null 2>&1; then
                print_success "OCR服务启动成功"
                return 0
            fi
            sleep 2
        done
        
        print_error "OCR服务启动失败"
        return 1
    fi
}

# 启动Web服务
start_web_service() {
    print_info "启动Web服务..."
    
    cd "$SCRIPT_DIR"
    
    # 检查依赖
    if ! python3 -c "import fastapi" 2>/dev/null; then
        print_warning "安装FastAPI依赖..."
        pip install fastapi uvicorn python-multipart requests
    fi
    
    # 启动服务
    print_info "Web服务启动中..."
    python3 -m uvicorn ocr_api_service:app \
        --host "0.0.0.0" \
        --port "${WEB_SERVICE_PORT}" \
        --reload &
    
    WEB_PID=$!
    echo $WEB_PID > /tmp/ocr_web_service.pid
    
    # 等待服务启动
    for i in {1..15}; do
        if curl -s "http://localhost:${WEB_SERVICE_PORT}/api/ocr/health" > /dev/null 2>&1; then
            print_success "Web服务启动成功"
            return 0
        fi
        sleep 1
    done
    
    print_error "Web服务启动失败"
    return 1
}

# 显示服务信息
show_service_info() {
    echo ""
    echo "========================================"
    echo "服务信息"
    echo "========================================"
    echo ""
    echo "🌐 Web服务地址:"
    echo "   本地访问: http://localhost:${WEB_SERVICE_PORT}"
    echo "   局域网访问: http://$(hostname -I | awk '{print $1}'):${WEB_SERVICE_PORT}"
    echo ""
    echo "📄 OCR服务地址:"
    echo "   http://localhost:${OCR_SERVICE_PORT}"
    echo ""
    echo "🔧 API端点:"
    echo "   健康检查: http://localhost:${WEB_SERVICE_PORT}/api/ocr/health"
    echo "   上传文件: http://localhost:${WEB_SERVICE_PORT}/api/ocr/upload"
    echo "   任务状态: http://localhost:${WEB_SERVICE_PORT}/api/ocr/status/{task_id}"
    echo "   处理结果: http://localhost:${WEB_SERVICE_PORT}/api/ocr/result/{task_id}"
    echo ""
    echo "📁 输出目录:"
    echo "   /home/l/知识库测试资料/ocr_results/"
    echo ""
    echo "========================================"
    echo "服务已启动，按 Ctrl+C 停止"
    echo "========================================"
    echo ""
}

# 清理函数
cleanup() {
    echo ""
    print_info "正在停止服务..."
    
    if [ -f /tmp/ocr_web_service.pid ]; then
        WEB_PID=$(cat /tmp/ocr_web_service.pid)
        kill $WEB_PID 2>/dev/null
        rm /tmp/ocr_web_service.pid
        print_success "Web服务已停止"
    fi
    
    echo ""
    print_success "服务已停止"
    exit 0
}

# 注册清理函数
trap cleanup SIGINT SIGTERM

# 主函数
main() {
    echo "OCR Web服务启动脚本"
    echo "版本: 1.0.0"
    echo ""
    
    # 检查OCR服务
    if ! check_ocr_service; then
        print_error "OCR服务启动失败，退出"
        exit 1
    fi
    
    echo ""
    
    # 启动Web服务
    if ! start_web_service; then
        print_error "Web服务启动失败，退出"
        exit 1
    fi
    
    echo ""
    
    # 显示服务信息
    show_service_info
    
    # 保持运行
    wait
}

# 运行主函数
main "$@"