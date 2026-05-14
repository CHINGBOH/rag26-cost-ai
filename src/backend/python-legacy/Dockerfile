FROM python:3.11-slim

WORKDIR /app

# 阿里云 apt 镜像 (Debian trixie deb822 格式)
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 清华 pip 镜像
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 预装 CPU 版 torch (~200MB, 比默认 GPU 版小 10 倍)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.llm.txt .
RUN pip install --no-cache-dir -r requirements.llm.txt

RUN pip install --no-cache-dir \
    qdrant-client \
    elasticsearch \
    neo4j-driver \
    redis \
    sentence-transformers \
    transformers \
    pydantic-settings \
    pyyaml

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
