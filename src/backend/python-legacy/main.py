"""
RAG Dashboard 后端服务入口
统一 API + 四库联动
"""

import sys
import os

# 添加项目根目录到路径 (rag-dashboard)
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(current_dir))
)  # src/backend/python-legacy -> src/backend -> src -> rag-dashboard
sys.path.insert(0, project_root)
# 添加当前目录
sys.path.insert(0, current_dir)

# 使用统一 API
from config.runtime import read_runtime_config
from api.unified_api import app

runtime_config = read_runtime_config()
display_host = "localhost" if runtime_config.api_host == "0.0.0.0" else runtime_config.api_host

if __name__ == "__main__":
    import uvicorn

    print(f"""
╔═══════════════════════════════════════════════════════════╗
║     RAG Dashboard Backend (Unified API)                   ║
║                                                           ║
║     API:     http://{display_host}:{runtime_config.api_port}                        ║
║     Docs:    http://{display_host}:{runtime_config.api_port}/docs                   ║
║     Health:  http://{display_host}:{runtime_config.api_port}/health                 ║
║                                                           ║
║     Features:                                             ║
║     • 四库联动 (Qdrant/ES/Neo4j/Redis)                    ║
║     • 召回精排 Pipeline                                   ║
║     • WebSocket 实时通信                                  ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        "main:app",
        host=runtime_config.api_host,
        port=runtime_config.api_port,
        reload=runtime_config.api_reload,
        log_level=runtime_config.log_level.lower(),
    )
