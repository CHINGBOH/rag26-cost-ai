"""
Retrieval Service - FastAPI 入口
端口: 8002
"""

import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

# ── Bypass SOCKS/HTTP proxy for localhost backing services ──
# Many dev machines have ALL_PROXY=socks://… set globally; without NO_PROXY
# the QdrantClient (httpx-based) tries to tunnel localhost through SOCKS and
# fails with "Unknown scheme for proxy URL". Be explicit before any client
# is constructed.
_LOCAL_HOSTS = "localhost,127.0.0.1,0.0.0.0,::1,host.docker.internal"
_existing_no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
_merged_no_proxy = ",".join(filter(None, [_existing_no_proxy, _LOCAL_HOSTS]))
os.environ["NO_PROXY"] = _merged_no_proxy
os.environ["no_proxy"] = _merged_no_proxy

# httpx still respects ALL_PROXY/socks even when NO_PROXY matches the host
# in some versions. Since every backend (Postgres/Qdrant/ES/Neo4j/Redis/TEI)
# we contact lives on localhost or inside the docker network, drop these.
for _k in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
           "HTTPS_PROXY", "https_proxy", "FTP_PROXY", "ftp_proxy"):
    os.environ.pop(_k, None)

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
from app.tools_api import router as tools_router
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


# Lightweight in-memory request metrics for /api/v1/ops/metrics
@app.middleware("http")
async def _metrics_middleware(request, call_next):
    import time as _t
    from app.api import ops_record_request

    t0 = _t.monotonic()
    response = await call_next(request)
    dur_ms = (_t.monotonic() - t0) * 1000.0
    try:
        ops_record_request(dur_ms, response.status_code, request.url.path)
    except Exception:
        pass
    return response


app.include_router(router)
app.include_router(tools_router)

# OpenTelemetry — opt-in via OTEL_EXPORTER_OTLP_ENDPOINT (#87 P4)
try:
    from app.telemetry import init_telemetry
    init_telemetry(app)
except Exception as _otel_exc:  # never block startup on tracing
    logger.warning(f"telemetry init failed: {_otel_exc}")
