FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖并安装（优先使用已有的 requirements.llm.txt 作为基础）
COPY requirements.llm.txt .
RUN pip install --no-cache-dir -r requirements.llm.txt

# 额外安装四库相关依赖
RUN pip install --no-cache-dir \
    qdrant-client \
    elasticsearch \
    neo4j-driver \
    redis \
    sentence-transformers \
    transformers \
    pydantic-settings \
    pyyaml

# 复制代码
COPY . .

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
