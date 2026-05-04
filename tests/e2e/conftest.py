"""
Pytest 配置和 fixtures for E2E tests
"""
import sys
import os
import asyncio
import pytest
import logging
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src" / "backend" / "retrieval-service"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Disable SOCKS/HTTP proxy for localhost (like main.py does)
_LOCAL_HOSTS = "localhost,127.0.0.1,0.0.0.0,::1,host.docker.internal"
_existing_no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
_merged_no_proxy = ",".join(filter(None, [_existing_no_proxy, _LOCAL_HOSTS]))
os.environ["NO_PROXY"] = _merged_no_proxy
os.environ["no_proxy"] = _merged_no_proxy

# Drop proxy env vars for localhost backing services
for _k in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
           "HTTPS_PROXY", "https_proxy", "FTP_PROXY", "ftp_proxy"):
    os.environ.pop(_k, None)


# Load environment
def _load_env():
    env_path = project_root / '.env'
    if not env_path.exists():
        logger.warning(f"⚠️  .env not found at {env_path}")
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


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def db_pool():
    """Get database connection pool"""
    try:
        from infrastructure.adapters.unified import UnifiedStore
        store = UnifiedStore()
        if store.pg_pool:
            logger.info("✅ Database pool created")
            yield store.pg_pool
        else:
            logger.error("❌ Failed to create database pool")
            yield None
        store.close()
    except Exception as e:
        logger.error(f"❌ Failed to initialize database: {e}")
        yield None


@pytest.fixture
def http_client():
    """Create HTTP client for API testing"""
    import requests
    
    session = requests.Session()
    # Disable proxy for localhost
    session.trust_env = False
    
    yield session
    session.close()


@pytest.fixture
def base_url():
    """Base URL for API tests"""
    return "http://localhost:8002"


@pytest.fixture
def test_data():
    """Common test data"""
    return {
        "broken_query": "broken_query_" + str(os.urandom(4).hex()),
        "test_problem_id": "test_problem_" + str(os.urandom(4).hex()),
        "test_route": "R1_navigator_dict",
    }
