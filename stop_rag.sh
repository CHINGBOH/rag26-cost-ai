#!/bin/bash
# RAG系统停止脚本

set -e

echo "=========================================="
echo "RAG系统停止脚本"
echo "=========================================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 停止API服务
if [ -f "/tmp/rag_api.pid" ]; then
    API_PID=$(cat /tmp/rag_api.pid)
    if ps -p $API_PID > /dev/null; then
        echo -e "${YELLOW}停止RAG API服务 (PID: $API_PID)...${NC}"
        kill $API_PID
        echo -e "${GREEN}✓ RAG API服务已停止${NC}"
    fi
    rm /tmp/rag_api.pid
fi

# 停止Docker容器
echo -e "${YELLOW}停止Docker容器...${NC}"

containers=("rag-postgres" "rag-redis" "rag-qdrant" "rag-neo4j" "rag-elasticsearch" "rag-minio" "rag-rabbitmq")

for container in "${containers[@]}"; do
    if docker ps | grep -q $container; then
        echo "停止 $container..."
        docker stop $container
        echo -e "${GREEN}✓ $container 已停止${NC}"
    else
        echo -e "${YELLOW}$container 未运行${NC}"
    fi
done

# 询问是否删除容器
read -p "是否删除Docker容器？(y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}删除Docker容器...${NC}"
    
    for container in "${containers[@]}"; do
        if docker ps -a | grep -q $container; then
            echo "删除 $container..."
            docker rm $container
            echo -e "${GREEN}✓ $container 已删除${NC}"
        fi
    done
fi

# 询问是否删除数据卷
read -p "是否删除数据卷？(这将删除所有数据！)(y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}删除数据卷...${NC}"
    
    rm -rf postgres_data redis_data qdrant_storage neo4j_data neo4j_logs es_data minio_data rabbitmq_data
    
    echo -e "${GREEN}✓ 数据卷已删除${NC}"
fi

echo "=========================================="
echo -e "${GREEN}RAG系统已停止${NC}"
echo "=========================================="