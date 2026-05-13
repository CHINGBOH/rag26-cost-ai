# Server Deployment Guide

> One-command Docker deployment for RAG Dashboard.
> Intended for use on a fresh Linux server with Docker ≥ 24 and Docker Compose v2.

---

## Prerequisites

| Requirement | Version | Check |
|---|---|---|
| Docker Engine | ≥ 24 | `docker --version` |
| Docker Compose plugin | ≥ v2.20 | `docker compose version` |
| Git | any | `git --version` |
| RAM | ≥ 8 GB | `free -h` |
| Disk | ≥ 20 GB free | `df -h` |

> **GPU (optional):** The embedding service (`tei`) uses NVIDIA GPU by default.
> If no GPU is available, set `EMBEDDING_BACKEND=local` in `.env` and remove
> the `tei` service from `docker-compose.yml` (or use `--scale tei=0`).

---

## Quick Start (5 steps)

### 1. Clone the repo

```bash
git clone https://github.com/CHINGBOH/RAG26.git rag-dashboard
cd rag-dashboard
```

### 2. Create `.env`

```bash
cp config/.env.example .env
```

Then edit `.env` — **at minimum set these values:**

```bash
# --- Required secrets ---
AUTH_SECRET=<random-32-char-string>        # Node auth JWT secret
POSTGRES_PASSWORD=<strong-password>
NEO4J_PASSWORD=<strong-password>

# --- LLM provider (pick one) ---
VITE_ACTIVE_LLM_PROVIDER=deepseek          # deepseek | kimi | openai
VITE_DEEPSEEK_API_KEY=<your-key>
# VITE_KIMI_API_KEY=<your-key>
# VITE_OPENAI_API_KEY=<your-key>

# --- Embedding backend ---
# If no GPU: set EMBEDDING_BACKEND=local (uses sentence-transformers on CPU)
# If GPU available: set EMBEDDING_BACKEND=tei (default, uses HuggingFace TEI)
EMBEDDING_BACKEND=local
```

> Full env reference: [`config/.env.example`](config/.env.example)

### 3. Build and start all services

```bash
docker compose up -d --build
```

This starts: **PostgreSQL · Redis · Qdrant · Elasticsearch · Python legacy ·
Retrieval service · Node orchestrator · Go Gateway · Go WebSocket · Frontend (nginx)**

First build takes 5–15 minutes. Subsequent starts are fast (images cached).

### 4. Run database migrations

```bash
# Wait for postgres to be healthy first
docker compose exec postgres pg_isready -U rag_user -d rag_dashboard

# Apply migrations
docker compose exec postgres psql -U rag_user -d rag_dashboard \
  -f /docker-entrypoint-initdb.d/01_init_database.sql 2>/dev/null || true
```

> Migrations in `sql/init/` are auto-applied on first start via Docker's
> `docker-entrypoint-initdb.d` mechanism. This step is only needed if you
> need to re-apply them manually.

### 5. Verify

```bash
# All containers should be Up (not Exiting)
docker compose ps

# Frontend accessible
curl -s -o /dev/null -w "%{http_code}" http://localhost/

# Backend health
curl -s http://localhost:8080/health | python3 -m json.tool
```

**Frontend URL: `http://<your-server-ip>/`**

---

## Service ports

| Service | Container port | Host port | Notes |
|---|---|---|---|
| Frontend (nginx) | 80 | **80** | Entry point — serves SPA + proxies API |
| Go API Gateway | 8080 | 8080 | Direct gateway access (optional) |
| Go WebSocket | 8081 | 8081 | WebSocket broadcast |
| Node orchestrator | 3001 | 3001 | |
| Python legacy | 8000 | 8000 | Embedding & ingestion |
| Retrieval service | 8002 | 8002 | Search, rerank, agent APIs |
| PostgreSQL | 5432 | 5432 | |
| Redis | 6379 | 6379 | |
| Qdrant | 6333 | 6333 | Vector DB |
| Elasticsearch | 9200 | 9200 | Keyword search |

---

## Useful commands

```bash
# View all logs at once
docker compose logs -f

# View logs for a specific service
docker compose logs -f retrieval-service
docker compose logs -f frontend

# Restart a single service after code change
docker compose up -d --build retrieval-service

# Stop everything (data volumes preserved)
docker compose down

# Stop and wipe all data volumes (destructive!)
docker compose down -v

# Check health of a container
docker inspect --format='{{.State.Health.Status}}' rag-postgres
```

---

## Updating to a new version

```bash
git pull
docker compose up -d --build
```

Docker rebuilds only the services whose source changed.

---

## Troubleshooting

### Frontend shows blank page or 502
- Check Go gateway is healthy: `docker compose logs go-gateway`
- Check frontend nginx logs: `docker compose logs frontend`
- Ensure all backend services are `Up (healthy)`: `docker compose ps`

### `python-legacy` or `retrieval-service` exits immediately
- Usually a missing env var or failed DB connection.
- Check: `docker compose logs python-legacy`
- Verify `.env` has correct `POSTGRES_PASSWORD` and `QDRANT_HOST=qdrant`

### `tei` (embedding) keeps restarting
- No GPU available. Set `EMBEDDING_BACKEND=local` in `.env` and restart:
  ```bash
  docker compose up -d --scale tei=0 python-legacy retrieval-service
  ```

### Port 80 already in use
- Another web server (nginx/apache) is running on the host.
- Either stop it or change the frontend port in `docker-compose.yml`:
  ```yaml
  frontend:
    ports:
      - "3000:80"   # expose on 3000 instead
  ```

### Postgres password mismatch
- If you changed `POSTGRES_PASSWORD` after first run, the volume still has
  the old password. Wipe and recreate: `docker compose down -v && docker compose up -d`

---

## Architecture (Docker network)

```
Browser
  └─> :80  frontend (nginx)
        ├─> /api/agent  → node-server:3001
        ├─> /api/v1/*   → retrieval-service:8002
        ├─> /api/*      → go-gateway:8080
        └─> /ws         → go-websocket:8081

go-gateway:8080
  ├─> node-server:3001
  ├─> python-legacy:8000
  └─> retrieval-service:8002
```

All containers communicate over the internal `rag-network` bridge network.
Only the ports listed in "Service ports" above are exposed to the host.
