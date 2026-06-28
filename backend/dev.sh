#!/usr/bin/env bash
set -euo pipefail
# Resolve the script's directory as an absolute path regardless of invocation CWD
SCRIPT_DIR="$( cd "$(dirname "$0")" && pwd )"
cd "$SCRIPT_DIR"
# Use the project venv's uvicorn — it has cerebras, Pillow, anthropic, etc.
exec "$SCRIPT_DIR/venv/bin/uvicorn" main:app --reload --host 0.0.0.0 --port 8000
