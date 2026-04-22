"""
Docker Python 沙箱 — 安全执行 Agent 生成的 Python 代码

安全防线：
  1. AST 静态检查（容器内 sandbox_entry.py）
  2. 受限 builtins（容器内）
  3. --network=none（无网络）
  4. --memory=256m（内存上限）
  5. --read-only + 超时 10s（只读文件系统 + 强杀）
"""

import json
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = "rag-sandbox:latest"
SANDBOX_TIMEOUT = 15  # 秒（Docker stop-timeout=10，留 5s buffer）
SANDBOX_MEMORY = "256m"
SANDBOX_CPUS = "1"


def _check_image_exists() -> bool:
    """检查沙箱镜像是否存在"""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", SANDBOX_IMAGE],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def execute_python(code: str) -> dict:
    """
    在 Docker 沙箱中执行 Python 代码

    Args:
        code: Python 代码字符串

    Returns:
        dict: {"status": "success"|"error", "result": str, "output": str, ...}
    """
    if not code or not code.strip():
        return {"status": "error", "error": "代码为空", "output": ""}

    # 检查镜像
    if not _check_image_exists():
        logger.error(f"沙箱镜像 {SANDBOX_IMAGE} 不存在，请先构建")
        return {
            "status": "error",
            "error": f"沙箱镜像 {SANDBOX_IMAGE} 不存在。请运行: "
                     f"cd src/backend/retrieval-service/infrastructure && "
                     f"docker build -t rag-sandbox:latest -f Dockerfile.sandbox .",
            "output": "",
        }

    # 构建 Docker 命令
    docker_cmd = [
        "docker", "run",
        "--rm",                       # 执行完自动删除容器
        "-i",                         # 从 stdin 读取输入
        "--network=none",             # 🔒 无网络
        f"--memory={SANDBOX_MEMORY}", # 🔒 内存限制
        f"--cpus={SANDBOX_CPUS}",     # 🔒 CPU 限制
        "--read-only",                # 🔒 只读文件系统
        "--tmpfs=/tmp:size=10m",      # 给 /tmp 一点临时空间（Python 需要）
        "--stop-timeout=10",          # 10 秒后强杀
        "--pids-limit=50",            # 🔒 限制进程数（防 fork bomb）
        "--security-opt=no-new-privileges",  # 🔒 禁止提权
        SANDBOX_IMAGE,
    ]

    input_json = json.dumps({"code": code}, ensure_ascii=False)

    try:
        logger.info(f"[sandbox] executing code ({len(code)} chars)")
        result = subprocess.run(
            docker_cmd,
            input=input_json,
            capture_output=True,
            text=True,
            timeout=SANDBOX_TIMEOUT,
        )

        if result.returncode != 0 and not result.stdout.strip():
            stderr = result.stderr.strip()[-300:]
            logger.warning(f"[sandbox] container exited with code {result.returncode}: {stderr}")
            return {
                "status": "error",
                "error": f"容器执行失败 (exit={result.returncode}): {stderr}",
                "output": "",
            }

        # 解析容器输出
        try:
            output = json.loads(result.stdout)
            log_result = output.get("result", "")[:80]
            logger.info(f"[sandbox] {output['status']}: {log_result}")
            return output
        except json.JSONDecodeError:
            # 容器输出不是 JSON（可能被 OOM kill 等异常中断）
            stdout_tail = result.stdout.strip()[-200:]
            return {
                "status": "error",
                "error": f"容器输出无法解析: {stdout_tail}",
                "output": result.stdout[:500],
            }

    except subprocess.TimeoutExpired:
        logger.warning("[sandbox] execution timed out")
        return {
            "status": "error",
            "error": f"执行超时（{SANDBOX_TIMEOUT}秒），可能有死循环",
            "output": "",
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "error": "docker 命令不可用，请确认 Docker 已安装",
            "output": "",
        }
    except Exception as e:
        logger.error(f"[sandbox] unexpected error: {e}")
        return {
            "status": "error",
            "error": f"沙箱异常: {type(e).__name__}: {e}",
            "output": "",
        }
