#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -x "/usr/local/bin/python3" ] && /usr/local/bin/python3 -c "import uvicorn, starlette" 2>/dev/null; then
  PYTHON_BIN="/usr/local/bin/python3"
elif python3 -c "import uvicorn, starlette" 2>/dev/null; then
  PYTHON_BIN="python3"
else
  echo "Installing dependencies into current python3 environment..."
  python3 -m pip install -r requirements.txt
  PYTHON_BIN="python3"
fi

echo "Starting NovaFlow AI using: $PYTHON_BIN"
exec "$PYTHON_BIN" run.py
