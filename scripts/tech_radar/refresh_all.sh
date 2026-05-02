#!/usr/bin/env bash
# refresh_all.sh — 一键拉所有外部源进 tech_radar (#94 I5)
# 用法: ./scripts/tech_radar/refresh_all.sh
# 建议挂 cron: 每天一次

set -e
cd "$(dirname "$0")/../.."

echo "=== arxiv ==="
python scripts/tech_radar/fetch_arxiv.py --days 7 --max 60 || echo "arxiv failed"

echo "=== huggingface ==="
python scripts/tech_radar/fetch_hf.py --limit 30 || echo "hf failed"

echo "=== github ==="
python scripts/tech_radar/fetch_github.py --per-repo 2 || echo "github failed"

echo "=== topology after refresh ==="
python scripts/topology_health.py | tail -10
