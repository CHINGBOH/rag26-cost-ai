FROM python:3.11-slim

WORKDIR /app

# 阿里云 apt 镜像 (Debian trixie deb822 格式)
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 清华 pip 镜像
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 预装 CPU 版 torch
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
