# COPILOT_DEPLOY.md — Instructions for GitHub Copilot CLI on a bare server

> **This file is written for you, the Copilot agent.**
> The user has just SSHed into a fresh Linux server and asked you to deploy this
> RAG Dashboard. Follow the steps below in order. Run each command, verify it
> succeeded, then move to the next. Do not skip verification steps.

---

## Your mission

Deploy RAG Dashboard on a bare Linux server from scratch.  
Key files to know:
- `DEPLOY.md` — full human-readable guide (reference when you need detail)
- `docker-compose.yml` — main services (default: lightweight mode)
- `docker-compose.2g.yml` — 2 GB RAM override (small models + memory limits)
- `config/.env.example` — all environment variables with comments

---

## Step 0 — Detect the server

Run these first. The results decide which profile to use.

```bash
# RAM (in MB)
free -m | awk '/^Mem:/{print $2}'

# CPU cores
nproc

# Disk free
df -h /

# OS
cat /etc/os-release | grep PRETTY_NAME
```

**Decision table:**

| RAM | Profile to use |
|---|---|
| < 3 GB | **2G mode** — use `docker-compose.2g.yml` override |
| 3–8 GB | **Lightweight** — `docker compose up -d` (no override) |
| > 8 GB | **Full** — `docker compose --profile full up -d` |

---

## Step 1 — Install prerequisites

### 1a. System packages

```bash
apt update && apt upgrade -y
apt install -y curl wget git unzip gnupg ca-certificates lsb-release
```

> CentOS/RHEL: replace `apt` with `dnf`.

### 1b. Add swap (mandatory if RAM < 8 GB)

```bash
SWAP_SIZE="6G"   # use 6G for 2GB servers, 4G for 4-8GB servers
fallocate -l $SWAP_SIZE /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
echo 'vm.swappiness=10' >> /etc/sysctl.conf
sysctl -p
swapon --show
```

Verify: `swapon --show` must list `/swapfile`.

### 1c. Install Docker CE

```bash
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker --version
docker compose version
```

Verify: both commands must print a version number.

---

## Step 2 — Clone the repo

```bash
cd /opt
git clone https://github.com/CHINGBOH/RAG26.git rag-dashboard
cd /opt/rag-dashboard
```

Verify: `ls` shows `docker-compose.yml`, `DEPLOY.md`, `src/`, etc.

---

## Step 3 — Create the .env file

```bash
cp config/.env.example .env
```

### 3a. Mandatory secrets — generate and write them now

```bash
# Generate secrets
SECRET_KEY=$(openssl rand -hex 32)
JWT_SECRET=$(openssl rand -hex 32)
POSTGRES_PASSWORD=$(openssl rand -hex 16)
MINIO_SECRET=$(openssl rand -hex 16)

# Write into .env
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" .env
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$JWT_SECRET|" .env
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$POSTGRES_PASSWORD|" .env
sed -i "s|^MINIO_SECRET_KEY=.*|MINIO_SECRET_KEY=$MINIO_SECRET|" .env
```

### 3b. LLM API key (needed for the AI to answer questions)

Ask the user which provider they use and set the key:

```bash
# Example for DeepSeek:
sed -i "s|^DEEPSEEK_API_KEY=.*|DEEPSEEK_API_KEY=<key_from_user>|" .env

# Example for OpenAI:
sed -i "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=<key_from_user>|" .env
```

### 3c. If RAM < 3 GB — switch to small models

```bash
sed -i "s|^EMBEDDING_MODEL_NAME=.*|EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5|" .env
sed -i "s|^RERANKER_MODEL_NAME=.*|RERANKER_MODEL_NAME=BAAI/bge-reranker-base|" .env
sed -i "s|^EMBEDDING_BACKEND=.*|EMBEDDING_BACKEND=local|" .env
```

---

## Step 4 — Start the stack

### If RAM < 3 GB (2G mode)

```bash
docker compose -f docker-compose.yml -f docker-compose.2g.yml up -d --build
```

### If RAM 3–8 GB (lightweight, default)

```bash
docker compose up -d --build
```

### If RAM > 8 GB (full, with Elasticsearch + TEI)

```bash
docker compose --profile full up -d --build
```

The first `--build` takes 5–15 minutes (downloading models, building images).  
Run `docker compose logs -f` to watch progress. Press Ctrl-C to detach from logs.

---

## Step 5 — Verify all services are up

```bash
docker compose ps
```

Expected: all containers show `Up` or `healthy`. Containers that are `Exit` or `Restarting` need investigation.

```bash
# Quick health check on each service
curl -s http://localhost:8000/health | python3 -m json.tool   # python-legacy
curl -s http://localhost:8002/health | python3 -m json.tool   # retrieval-service
curl -s http://localhost:3001/health | python3 -m json.tool   # node-server
curl -s http://localhost:8080/health                           # go-gateway
curl -s http://localhost:80                                    # frontend (nginx)
```

All should return HTTP 200 or a JSON `{"status":"ok"}` response.

---

## Step 6 — Open the firewall

```bash
# Ubuntu/Debian (ufw)
ufw allow 80/tcp
ufw allow 443/tcp
ufw reload

# CentOS/RHEL (firewalld)
firewall-cmd --permanent --add-port=80/tcp
firewall-cmd --permanent --add-port=443/tcp
firewall-cmd --reload
```

---

## Step 7 — Tell the user the URL

```
Frontend:  http://<server-public-ip>/
API docs:  http://<server-public-ip>/api/docs
```

Get the public IP if you don't know it:
```bash
curl -s ifconfig.me
```

---

## Troubleshooting — common failures

### Container exits immediately (OOM)

```bash
docker compose logs <service-name> | tail -30
dmesg | grep -i "killed process" | tail -5
```

Fix: if OOM, reduce models or add more swap (see Step 1b).

### Embedding model download fails (no internet / slow)

```bash
docker compose logs python-legacy | grep -i "download\|error\|failed"
```

Fix: The model downloads from HuggingFace on first start. If the server has no internet access, pre-download the model and mount it, or use a proxy.

### Port already in use

```bash
ss -tlnp | grep ':80\|:8000\|:8002\|:3001\|:8080'
```

Fix: Stop the conflicting process or change the port in `.env`.

### PostgreSQL not starting

```bash
docker compose logs postgres | tail -20
```

Fix: often a data directory permission issue. `rm -rf postgres_data/ && docker compose up -d postgres`

### All services healthy but frontend shows blank page

```bash
curl -I http://localhost:80/
docker compose logs frontend | tail -20
```

Fix: nginx config error or React build failure. Check `docker compose logs frontend`.

---

## Useful commands during operation

```bash
# Live logs
docker compose logs -f

# Restart one service
docker compose restart <service-name>

# Stop everything
docker compose down

# Stop + remove volumes (destructive!)
docker compose down -v

# Check RAM usage right now
docker stats --no-stream

# Update to latest code
git pull && docker compose up -d --build
```

---

## Reference

| File | Purpose |
|---|---|
| `DEPLOY.md` | Full human guide with OS setup, firewall, SSL, etc. |
| `docker-compose.yml` | Main services |
| `docker-compose.2g.yml` | 2 GB RAM override |
| `config/.env.example` | All env vars documented |
| `.github/copilot-instructions.md` | Your general instructions for this repo |
