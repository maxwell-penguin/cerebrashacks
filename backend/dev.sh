#!/usr/bin/env bash
set -euo pipefail
# Resolve the script's directory as an absolute path regardless of invocation CWD
SCRIPT_DIR="$( cd "$(dirname "$0")" && pwd )"
cd "$SCRIPT_DIR"

# Prefer the project venv if it exists fall back to whatever uvicorn is on PATH
if [ -f "$SCRIPT_DIR/venv/bin/uvicorn" ]; then
    UVICORN="$SCRIPT_DIR/venv/bin/uvicorn"
elif [ -f "$SCRIPT_DIR/.venv/bin/uvicorn" ]; then
    UVICORN="$SCRIPT_DIR/.venv/bin/uvicorn"
elif command -v uvicorn &>/dev/null; then
    UVICORN="uvicorn"
else
    echo "ERROR: uvicorn not found. Create a venv and install requirements.txt first." >&2
    exit 1
fi

exec "$UVICORN" main:app --reload --host 0.0.0.0 --port 8000
