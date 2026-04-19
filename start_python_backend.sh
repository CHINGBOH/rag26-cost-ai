#!/bin/bash
cd /home/l/rag-dashboard
source venv/bin/activate
cd src/backend/python-legacy
# Unset proxy environment variables
unset ALL_PROXY
unset all_proxy
export HTTP_PROXY=""
export HTTPS_PROXY=""
export NO_PROXY="localhost,127.0.0.0/8,::1"
# Start backend
python -m uvicorn main:app --reload --port 8000 2>&1