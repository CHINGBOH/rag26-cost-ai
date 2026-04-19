# ============================================================
# PaddleOCR + PPStructure + FastAPI 服务 Dockerfile (GPU版)
# 基于官方 PaddlePaddle 3.2 CUDA 12.6 镜像
# ============================================================

# 国内用户推荐用百度镜像源（更快）
# FROM ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddle:3.2.0-gpu-cuda12.6-cudnn9.5
FROM paddlepaddle/paddle:3.2.0-gpu-cuda12.6-cudnn9.5

WORKDIR /app

# 安装系统依赖（libgl1 是 OpenCV 等库必需的）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 提供 libcuda.so.1 stub，使 paddlepaddle-gpu 在无 GPU 驱动的宿主机/构建时也能加载
RUN ln -sf /usr/local/cuda/lib64/stubs/libcuda.so /usr/local/cuda/lib64/libcuda.so.1 && \
    ln -sf /usr/local/cuda/lib64/stubs/libcuda.so /usr/lib/x86_64-linux-gnu/libcuda.so.1 && \
    ldconfig

# 先拷贝 requirements 利用 Docker 缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 注意：无法在 build 阶段预下载 PaddleOCR 模型，因为 GPU 镜像在 build 时
# 缺少真实的 GPU 驱动。模型会在容器首次启动并收到请求时自动下载到 ~/.paddleocr/。
# 如需离线部署，可把已下载的模型挂载进容器。

# 创建输出目录（运行时可挂 volume）
RUN mkdir -p /app/ocr_outputs /app/logs

# 拷贝服务代码和启动脚本
COPY ocr_service.py .
COPY start.sh .
RUN chmod +x start.sh

# 服务端口
EXPOSE 8001

# 启动
CMD ["./start.sh"]
