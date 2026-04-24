"""
Retrieval Service - FastAPI 入口
端口: 8002
"""

import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

# Load .env from repo root (3 levels up from this file)
def _load_env():
    env_path = Path(__file__).parent.parent.parent.parent / '.env'
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v

_load_env()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router, set_services
from app.pipeline import UnifiedRetrievalPipeline
from infrastructure.adapters.unified import UnifiedStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局服务实例
_pipeline = None
_store = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pipeline, _store
    try:
        logger.info("Initializing UnifiedStore...")
        _store = UnifiedStore()
        logger.info("UnifiedStore initialized")
        logger.info("Initializing UnifiedRetrievalPipeline...")
        _pipeline = UnifiedRetrievalPipeline(_store)
        logger.info("UnifiedRetrievalPipeline initialized")
        set_services(_pipeline, _store)
        logger.info("✅ Retrieval Service ready on port 8002")
    except Exception as e:
        import traceback
        logger.warning(f"⚠️ Failed to initialize some services: {e}")
        logger.warning(f"Traceback: {traceback.format_exc()}")
        set_services(None, _store)
    yield
    if _store:
        _store.close()
        logger.info("✅ Retrieval Service shutdown")


app = FastAPI(
    title="Retrieval Service",
    description="独立检索微服务 - 向量/关键词/图谱混合检索、精排、评估、查询分解",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
