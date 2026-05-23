#!/bin/bash
# RAG26 CLI wrapper
exec python3 "$(dirname "$0")/tools/rag_cli.py" "$@"
