#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "ERROR: Python was not found on PATH."
    echo "Install Python 3.10+ (python.org, or your OS package manager) and try again."
    echo "See README.md -> Troubleshooting -> 'Python not found' for details."
    exit 1
fi

if [ ! -x "backend/.venv/bin/python" ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv backend/.venv
fi

echo "Installing pinned dependencies..."
backend/.venv/bin/pip install -q -r backend/requirements.txt

echo
STARTUP_OUT="$(backend/.venv/bin/python backend/scripts/startup_check.py)"
echo "$STARTUP_OUT"
PORT="$(echo "$STARTUP_OUT" | grep '^PORT=' | cut -d= -f2)"
PORT="${PORT:-8000}"

echo
echo "Starting the server on http://localhost:${PORT} ..."
(cd backend && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT") &
SERVER_PID=$!

sleep 2
if command -v open >/dev/null 2>&1; then
    open "http://localhost:${PORT}" || true
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://localhost:${PORT}" || true
else
    "$PYTHON" -m webbrowser "http://localhost:${PORT}" || true
fi

echo
echo "Server running (pid ${SERVER_PID}). Press Ctrl+C to stop it."
wait "$SERVER_PID"
