#!/bin/bash

# RAG系统启动脚本
# 按顺序启动所有服务

set -e

echo "🚀 RAG系统启动脚本"
echo "================================"

# 检查依赖
echo "📋 检查系统依赖..."

# 检查Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker未安装，请先安装Docker"
    exit 1
fi
echo "✓ Docker已安装"

# 检查Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose未安装，请先安装Docker Compose"
    exit 1
fi
echo "✓ Docker Compose已安装"

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3未安装"
    exit 1
fi
echo "✓ Python3已安装"

# 检查Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js未安装"
    exit 1
fi
echo "✓ Node.js已安装"

# 创建必要的目录
echo "📁 创建必要的目录..."
mkdir -p logs
mkdir -p data/postgresql
mkdir -p data/qdrant
mkdir -p data/redis
echo "✓ 目录创建完成"

# 构建Docker镜像
echo "🔨 构建Docker镜像..."
docker-compose -f docker-compose.production.yml build
echo "✓ Docker镜像构建完成"

# 启动基础服务
echo "🌐 启动基础服务（PostgreSQL, Qdrant, Redis）..."
docker-compose -f docker-compose.production.yml up -d postgres qdrant redis
echo "✓ 基础服务已启动"

# 等待基础服务就绪
echo "⏳ 等待基础服务就绪..."
sleep 10

# 启动Python服务
echo "🐍 启动Python服务（Embedding, Rerank, LLM）..."
docker-compose -f docker-compose.production.yml up -d embedding-service rerank-service llm-service
echo "✓ Python服务已启动"

# 等待Python服务就绪
echo "⏳ 等待Python服务就绪..."
sleep 30

# 启动Node.js编排器
echo "🎯 启动Node.js编排器..."
docker-compose -f docker-compose.production.yml up -d node-orchestrator
echo "✓ 编排器已启动"

# 等待编排器就绪
echo "⏳ 等待编排器就绪..."
sleep 10

# 启动前端服务
echo "🌐 启动前端服务..."
docker-compose -f docker-compose.production.yml up -d web-frontend
echo "✓ 前端服务已启动"

# 检查服务状态
echo "🔍 检查服务状态..."
docker-compose -f docker-compose.production.yml ps

echo ""
echo "================================"
echo "✅ RAG系统启动完成！"
echo "================================"
echo ""
echo "服务访问地址："
echo "  - 前端界面: http://localhost"
echo "  - 编排器API: http://localhost:3000"
echo "  - 编排器健康检查: http://localhost:3000/health"
echo "  - LLM服务: http://localhost:8003"
echo "  - LLM健康检查: http://localhost:8003/health"
echo ""
echo "查看日志："
echo "  docker-compose -f docker-compose.production.yml logs -f"
echo ""
echo "停止系统："
echo "  docker-compose -f docker-compose.production.yml down"
echo ""