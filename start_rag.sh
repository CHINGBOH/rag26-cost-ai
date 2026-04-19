#!/bin/bash
# RAG系统启动脚本

set -e

echo "=========================================="
echo "RAG系统启动脚本"
echo "=========================================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查Docker是否安装
if ! command -v docker &> /dev/null; then
    echo -e "${RED}错误: Docker未安装${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Docker已安装${NC}"

# 检查Docker Compose是否安装
if ! command -v docker-compose &> /dev/null; then
    echo -e "${YELLOW}警告: Docker Compose未安装，将使用docker命令${NC}"
fi

# 创建必要的目录
echo -e "${YELLOW}创建必要的目录...${NC}"
mkdir -p data/knowledge_base/raw_pdfs
mkdir -p data/knowledge_base/ocr_results/json
mkdir -p data/knowledge_base/ocr_results/text
mkdir -p data/knowledge_base/processed/chunks
mkdir -p data/knowledge_base/processed/embeddings
mkdir -p data/knowledge_base/processed/structured
mkdir -p data/knowledge_base/metadata
mkdir -p logs
mkdir -p postgres_data
mkdir -p redis_data
mkdir -p qdrant_storage
mkdir -p neo4j_data
mkdir -p neo4j_logs
mkdir -p es_data
mkdir -p minio_data
mkdir -p rabbitmq_data
mkdir -p sql/init

echo -e "${GREEN}✓ 目录创建完成${NC}"

# 检查网络
echo -e "${YELLOW}检查Docker网络...${NC}"
if ! docker network inspect rag-network &> /dev/null; then
    docker network create rag-network
    echo -e "${GREEN}✓ 网络创建完成${NC}"
else
    echo -e "${GREEN}✓ 网络已存在${NC}"
fi

# 启动基础设施服务
echo -e "${YELLOW}启动基础设施服务...${NC}"

# 启动PostgreSQL
if ! docker ps | grep -q rag-postgres; then
    echo "启动PostgreSQL..."
    docker run -d \
        --name rag-postgres \
        --network rag-network \
        -e POSTGRES_DB=rag_db \
        -e POSTGRES_USER=rag_user \
        -e POSTGRES_PASSWORD=rag_password \
        -p 5432:5432 \
        -v $(pwd)/postgres_data:/var/lib/postgresql/data \
        -v $(pwd)/sql/init:/docker-entrypoint-initdb.d \
        postgres:16-alpine
    
    echo -e "${GREEN}✓ PostgreSQL已启动${NC}"
else
    echo -e "${GREEN}✓ PostgreSQL已在运行${NC}"
fi

# 启动Redis
if ! docker ps | grep -q rag-redis; then
    echo "启动Redis..."
    docker run -d \
        --name rag-redis \
        --network rag-network \
        -p 6379:6379 \
        -v $(pwd)/redis_data:/data \
        redis:7.2-alpine \
        redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru
    
    echo -e "${GREEN}✓ Redis已启动${NC}"
else
    echo -e "${GREEN}✓ Redis已在运行${NC}"
fi

# 启动Qdrant
if ! docker ps | grep -q rag-qdrant; then
    echo "启动Qdrant..."
    docker run -d \
        --name rag-qdrant \
        --network rag-network \
        -p 6333:6333 \
        -p 6334:6334 \
        -v $(pwd)/qdrant_storage:/qdrant/storage \
        qdrant/qdrant:v1.8.0
    
    echo -e "${GREEN}✓ Qdrant已启动${NC}"
else
    echo -e "${GREEN}✓ Qdrant已在运行${NC}"
fi

# 启动Neo4j
if ! docker ps | grep -q rag-neo4j; then
    echo "启动Neo4j..."
    docker run -d \
        --name rag-neo4j \
        --network rag-network \
        -p 7474:7474 \
        -p 7687:7687 \
        -v $(pwd)/neo4j_data:/data \
        -v $(pwd)/neo4j_logs:/logs \
        -e NEO4J_AUTH=neo4j/rag_password \
        neo4j:5.16.0-community
    
    echo -e "${GREEN}✓ Neo4j已启动${NC}"
else
    echo -e "${GREEN}✓ Neo4j已在运行${NC}"
fi

# 启动Elasticsearch
if ! docker ps | grep -q rag-elasticsearch; then
    echo "启动Elasticsearch..."
    docker run -d \
        --name rag-elasticsearch \
        --network rag-network \
        -p 9200:9200 \
        -p 9300:9300 \
        -v $(pwd)/es_data:/usr/share/elasticsearch/data \
        -e discovery.type=single-node \
        -e xpack.security.enabled=false \
        -e "ES_JAVA_OPTS=-Xms1g -Xmx1g" \
        elasticsearch:8.12.0
    
    echo -e "${GREEN}✓ Elasticsearch已启动${NC}"
else
    echo -e "${GREEN}✓ Elasticsearch已在运行${NC}"
fi

# 启动MinIO
if ! docker ps | grep -q rag-minio; then
    echo "启动MinIO..."
    docker run -d \
        --name rag-minio \
        --network rag-network \
        -p 9000:9000 \
        -p 9001:9001 \
        -v $(pwd)/minio_data:/data \
        -v $(pwd)/data/knowledge_base:/kb_data \
        -e MINIO_ROOT_USER=rag_admin \
        -e MINIO_ROOT_PASSWORD=rag_password \
        minio/minio:latest \
        server /data --console-address ":9001"
    
    echo -e "${GREEN}✓ MinIO已启动${NC}"
else
    echo -e "${GREEN}✓ MinIO已在运行${NC}"
fi

# 启动RabbitMQ
if ! docker ps | grep -q rag-rabbitmq; then
    echo "启动RabbitMQ..."
    docker run -d \
        --name rag-rabbitmq \
        --network rag-network \
        -p 5672:5672 \
        -p 15672:15672 \
        -v $(pwd)/rabbitmq_data:/var/lib/rabbitmq \
        -e RABBITMQ_DEFAULT_USER=rag_user \
        -e RABBITMQ_DEFAULT_PASS=rag_password \
        rabbitmq:3.12-management-alpine
    
    echo -e "${GREEN}✓ RabbitMQ已启动${NC}"
else
    echo -e "${GREEN}✓ RabbitMQ已在运行${NC}"
fi

# 等待服务启动
echo -e "${YELLOW}等待服务启动...${NC}"
sleep 10

# 检查服务状态
echo -e "${YELLOW}检查服务状态...${NC}"

services=("rag-postgres" "rag-redis" "rag-qdrant" "rag-neo4j" "rag-elasticsearch" "rag-minio" "rag-rabbitmq")
all_running=true

for service in "${services[@]}"; do
    if docker ps | grep -q $service; then
        echo -e "${GREEN}✓ $service 运行正常${NC}"
    else
        echo -e "${RED}✗ $service 未运行${NC}"
        all_running=false
    fi
done

if [ "$all_running" = false ]; then
    echo -e "${RED}部分服务启动失败，请检查日志${NC}"
    exit 1
fi

# 安装Python依赖
echo -e "${YELLOW}安装Python依赖...${NC}"
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    echo -e "${GREEN}✓ Python依赖安装完成${NC}"
else
    echo -e "${YELLOW}未找到requirements.txt，跳过依赖安装${NC}"
fi

# 设置环境变量
echo -e "${YELLOW}设置环境变量...${NC}"
export REDIS_HOST=localhost
export REDIS_PORT=6379
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=rag_db
export POSTGRES_USER=rag_user
export POSTGRES_PASSWORD=rag_password
export QDRANT_HOST=localhost
export QDRANT_PORT=6333
export NEO4J_URI="bolt://neo4j:rag_password@localhost:7687"
export API_HOST=0.0.0.0
export API_PORT=8000

echo -e "${GREEN}✓ 环境变量设置完成${NC}"

# 启动API服务
echo -e "${YELLOW}启动RAG API服务...${NC}"
cd src/backend/python-legacy
python rag_api_service.py &
API_PID=$!

echo -e "${GREEN}✓ RAG API服务已启动 (PID: $API_PID)${NC}"

# 显示访问信息
echo "=========================================="
echo -e "${GREEN}RAG系统启动完成！${NC}"
echo "=========================================="
echo ""
echo "服务访问地址："
echo "  - API服务: http://localhost:8000"
echo "  - API文档: http://localhost:8000/docs"
echo "  - Qdrant: http://localhost:6333/dashboard"
echo "  - Neo4j: http://localhost:7474"
echo "  - Elasticsearch: http://localhost:9200"
echo "  - MinIO: http://localhost:9001"
echo "  - RabbitMQ: http://localhost:15672 (用户: rag_user, 密码: rag_password)"
echo ""
echo "停止服务："
echo "  - 停止API: kill $API_PID"
echo "  - 停止所有Docker容器: ./stop_rag.sh"
echo ""
echo "查看日志："
echo "  - API日志: tail -f logs/rag_api.log"
echo "  - Docker日志: docker logs <container_name>"
echo ""
echo "=========================================="

# 保存PID
echo $API_PID > /tmp/rag_api.pid

echo -e "${GREEN}启动脚本执行完成！${NC}"