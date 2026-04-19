#!/bin/bash

# Go网关启动脚本
set -e

cd "$(dirname "$0")"

# 设置Go代理（针对中国网络环境）
export GOPROXY=https://goproxy.cn,direct
export GO111MODULE=on

echo "🔧 启动RAG系统Go网关服务"

# 检查Go是否安装
if ! command -v go &> /dev/null; then
    echo "❌ Go未安装，请先安装Go 1.21+"
    echo "    Ubuntu/Debian: sudo apt-get install golang-go"
    echo "    macOS: brew install go"
    exit 1
fi

echo "✅ Go版本: $(go version)"

# 下载依赖
echo "📦 下载Go依赖..."
if ! go mod download; then
    echo "⚠️  依赖下载失败，尝试使用备用代理..."
    export GOPROXY=https://mirrors.aliyun.com/goproxy/,direct
    go mod download
fi

# 构建网关
echo "🏗️  构建网关程序..."
if ! go build -o gateway ./cmd/gateway; then
    echo "❌ 构建失败"
    exit 1
fi

echo "✅ 网关构建成功"

# 检查依赖服务是否运行
echo "🔍 检查依赖服务..."
SERVICES=(
    "Node.js后端:3001"
    "Python后端:8000"
)

ALL_HEALTHY=true
for service in "${SERVICES[@]}"; do
    name="${service%:*}"
    port="${service#*:}"
    if curl -s --max-time 2 "http://localhost:$port/health" > /dev/null; then
        echo "  ✅ $name (端口:$port) 正常"
    else
        echo "  ⚠️  $name (端口:$port) 不可达"
        ALL_HEALTHY=false
    fi
done

if [ "$ALL_HEALTHY" = false ]; then
    echo "⚠️  部分依赖服务未运行，网关可能无法正常工作"
fi

# 启动网关
echo "🚀 启动网关服务 (端口:8080)"
echo "📡 代理目标:"
echo "   - Node.js后端: http://localhost:3001"
echo "   - Python后端: http://localhost:8000"
echo ""
echo "🛑 按 Ctrl+C 停止网关"

export PORT=8080
export DEBUG=false
./gateway