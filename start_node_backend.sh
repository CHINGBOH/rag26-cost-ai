#!/bin/bash
cd /home/l/rag-dashboard/src/backend/server
# Unset proxy variables
unset ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy FTP_PROXY ftp_proxy
# Set required environment variables
export AUTH_SECRET="rag-dashboard-secret-key-change-in-production"
export DEFAULT_ADMIN_USERNAME="admin"
export DEFAULT_ADMIN_PASSWORD="admin123"
export PORT="3001"
# Start the server
exec npm run dev 2>&1