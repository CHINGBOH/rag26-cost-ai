# Server Deployment Guide

> Complete guide from a **bare Linux server** to a running RAG Dashboard.
> Covers OS preparation, Docker installation, and application deployment.

---

## Hardware requirements

| Resource | Minimum | Recommended |
|---|---|---|
| CPU | 4 cores | 8+ cores |
| RAM | 8 GB | 16 GB |
| Disk | 40 GB SSD | 100 GB SSD |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 / 24.04 LTS |
| GPU | — | NVIDIA (for TEI embedding) |

---

## Part 1 — Prepare the bare server

### 1.1 Update the system

```bash
apt update && apt upgrade -y
apt install -y curl wget git unzip gnupg ca-certificates lsb-release
```

> **CentOS / RHEL / AlmaLinux:**
> ```bash
> dnf update -y
> dnf install -y curl wget git unzip gnupg ca-certificates
> ```

### 1.2 Configure swap (if RAM < 16 GB)

Elasticsearch and the build step are memory-hungry. Add 4 GB swap as a safety net:

```bash
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
swapon --show
```

### 1.3 Tune kernel for Elasticsearch

```bash
sysctl -w vm.max_map_count=262144
echo 'vm.max_map_count=262144' >> /etc/sysctl.conf
```

### 1.4 Open firewall ports

```bash
# Ubuntu (ufw)
ufw allow 22/tcp      # SSH — keep this open!
ufw allow 80/tcp      # Frontend
ufw allow 8080/tcp    # Go API Gateway (optional direct access)
ufw enable
ufw status
```

> **CentOS / firewalld:**
> ```bash
> firewall-cmd --permanent --add-service=ssh
> firewall-cmd --permanent --add-port=80/tcp
> firewall-cmd --permanent --add-port=8080/tcp
> firewall-cmd --reload
> ```

---

## Part 2 — Install Docker Engine

### 2.1 Install Docker (Ubuntu / Debian)

```bash
# Add Docker's official GPG key and repository
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt update
apt install -y docker-ce docker-ce-cli containerd.io \
               docker-buildx-plugin docker-compose-plugin

# Start and enable Docker
systemctl start docker
systemctl enable docker
```

> **CentOS / RHEL:**
> ```bash
> dnf install -y dnf-plugins-core
> dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
> dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
> systemctl start docker && systemctl enable docker
> ```

### 2.2 (Optional) Run Docker without sudo

```bash
usermod -aG docker $USER
newgrp docker       # apply without logout
```

### 2.3 Verify

```bash
docker --version           # Docker version 24.x.x or higher
docker compose version     # Docker Compose version v2.x.x
docker run --rm hello-world
```

---

## Part 3 — (Optional) NVIDIA GPU support

Skip this section if your server has no GPU. Set `EMBEDDING_BACKEND=local` in `.env` instead.

### 3.1 Install NVIDIA driver

```bash
apt install -y ubuntu-drivers-common
ubuntu-drivers autoinstall
reboot
# After reboot:
nvidia-smi    # should show GPU info
```

### 3.2 Install NVIDIA Container Toolkit

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

apt update
apt install -y nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

# Verify
docker run --rm --gpus all nvidia/cuda:12.0-base-ubuntu22.04 nvidia-smi
```

---

## Part 4 — Deploy RAG Dashboard

### Prerequisites checklist

```bash
docker --version        # ≥ 24
docker compose version  # ≥ v2.20
git --version           # any
free -h                 # ≥ 8 GB total (RAM + swap)
df -h /                 # ≥ 40 GB free
```

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

Generate secure random secrets first:

```bash
# Generate AUTH_SECRET
openssl rand -hex 32

# Generate POSTGRES_PASSWORD (or pick your own strong password)
openssl rand -base64 20
```

Then edit `.env` — **at minimum set these values:**

```bash
# --- Required secrets ---
AUTH_SECRET=<output of openssl rand -hex 32>
POSTGRES_PASSWORD=<strong-password>
NEO4J_PASSWORD=<strong-password>

# --- LLM provider (pick one) ---
VITE_ACTIVE_LLM_PROVIDER=deepseek          # deepseek | kimi | openai
VITE_DEEPSEEK_API_KEY=sk-...
# VITE_KIMI_API_KEY=...
# VITE_OPENAI_API_KEY=...

# --- Embedding backend ---
# No GPU → local (CPU, slower but works)
# NVIDIA GPU available → tei (fast, uses HuggingFace TEI container)
EMBEDDING_BACKEND=local
```

> Full reference for every env var: [`config/.env.example`](config/.env.example)

### 3. Build and start all services

**Lightweight server (recommended for ≤ 8 GB RAM, no GPU, no OCR):**

```bash
# Starts: PostgreSQL · Redis · Qdrant · Python legacy · Retrieval ·
#         Node orchestrator · Go Gateway · Go WebSocket · Frontend
# Skips:  Elasticsearch, TEI embedding, Milvus, OCR service
EMBEDDING_BACKEND=local docker compose up -d --build
```

> Make sure `EMBEDDING_BACKEND=local` is also set in your `.env` file.

**Full server (≥ 16 GB RAM + NVIDIA GPU):**

```bash
docker compose --profile full up -d --build
```

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

## Deployment modes

| Mode | Command | Included services | RAM needed |
|---|---|---|---|
| **Lightweight** (default) | `docker compose up -d` | Core stack only (no ES, no TEI, no Milvus, no OCR) | ~4 GB |
| **Full** | `docker compose --profile full up -d` | All of the above + Elasticsearch + TEI (GPU) | ~12 GB + GPU |
| **Milvus** | `docker compose --profile milvus up -d` | Core stack + Milvus vector DB | ~6 GB |

> OCR service (`src/backend/ocr-service`) is intentionally excluded from all Docker Compose modes — it requires heavy PaddleOCR dependencies. Run it separately only if needed.

---

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
