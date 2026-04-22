#!/usr/bin/env python3
"""
OCR Pipeline 一键运行脚本
自动设置环境并启动处理
"""

import os
import sys

# 自动设置CUDA库路径
OLLAMA_CUDA = "/usr/local/lib/ollama/cuda_v12"
if os.path.exists(OLLAMA_CUDA):
    ld = os.environ.get("LD_LIBRARY_PATH", "")
    if OLLAMA_CUDA not in ld:
        os.environ["LD_LIBRARY_PATH"] = f"{OLLAMA_CUDA}:{ld}"

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from ocr_automation.cli import main

if __name__ == '__main__':
    main()
