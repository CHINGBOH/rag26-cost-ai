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
from api.unified_api import app

if __name__ == "__main__":
    import uvicorn

    print("""
╔═══════════════════════════════════════════════════════════╗
║     RAG Dashboard Backend (Unified API)                   ║
║                                                           ║
║     API:     http://localhost:8000                        ║
║     Docs:    http://localhost:8000/docs                   ║
║     Health:  http://localhost:8000/health                 ║
║                                                           ║
║     Features:                                             ║
║     • 四库联动 (Qdrant/ES/Neo4j/Redis)                    ║
║     • 召回精排 Pipeline                                   ║
║     • WebSocket 实时通信                                  ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """)

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
