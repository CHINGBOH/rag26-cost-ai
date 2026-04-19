#!/bin/bash
cd /home/l/rag-dashboard
source venv/bin/activate
cd src/backend/python-legacy
# Unset all proxy environment variables
unset ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy FTP_PROXY ftp_proxy
# Keep NO_PROXY
export NO_PROXY="localhost,127.0.0.0/8,::1,0.0.0.0,*.local"
# Start the server
exec python -m uvicorn main:app --reload --port 8000 2>&1