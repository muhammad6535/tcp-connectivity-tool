#!/usr/bin/env bash
# Start a local TCP listener for manual testing.
# Usage: ./scripts/start_server.sh [HOST] [PORT]
set -euo pipefail

HOST="${1:-127.0.0.1}"
PORT="${2:-8000}"

echo "Serving HTTP on ${HOST}:${PORT} (Ctrl+C to stop)"
exec python3 -m http.server "$PORT" --bind "$HOST"
