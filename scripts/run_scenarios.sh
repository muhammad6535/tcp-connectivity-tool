#!/usr/bin/env bash
# Reproduce the documented test scenarios on this machine.
# Writes real CSVs into samples/ and prints the observed exit codes.
#
# Usage: ./scripts/run_scenarios.sh
#        PORT=8001 ./scripts/run_scenarios.sh
set -u

cd "$(dirname "$0")/.."
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
OUT_DIR="${OUT_DIR:-samples}"
mkdir -p "$OUT_DIR"

SERVER_PID=""
CHECK_PID=""

stop_server() {
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    SERVER_PID=""
}

cleanup() {
    stop_server
    if [ -n "$CHECK_PID" ] && kill -0 "$CHECK_PID" 2>/dev/null; then
        kill "$CHECK_PID" 2>/dev/null || true
        wait "$CHECK_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

start_server() {
    python3 -m http.server "$PORT" --bind "$HOST" >/dev/null 2>&1 &
    SERVER_PID=$!
    # Give the listening socket time to bind.
    sleep 1
}

section() {
    printf '\n============================================================\n'
    printf '%s\n' "$1"
    printf '============================================================\n'
}

section "Scenario 1: server running on ${HOST}:${PORT}"
start_server
python3 tcp_check.py "$HOST" "$PORT" -n 5 -t 2 -i 0.2 -o "$OUT_DIR/sample_success.csv"
echo "exit_code=$?"

section "Scenario 2: server stopped (same port)"
stop_server
sleep 1
python3 tcp_check.py "$HOST" "$PORT" -n 3 -t 2 -i 0.2 -o "$OUT_DIR/sample_server_stopped.csv"
echo "exit_code=$?"

section "Scenario 3: unused port 8999"
python3 tcp_check.py "$HOST" 8999 -n 2 -t 2 -i 0.2 -o "$OUT_DIR/sample_unused_port.csv"
echo "exit_code=$?"

section "Scenario 4: stop server during repeated checks"
start_server
python3 tcp_check.py "$HOST" "$PORT" -n 10 -t 2 -i 1 -o "$OUT_DIR/sample_transition.csv" &
CHECK_PID=$!
sleep 3
stop_server
if wait "$CHECK_PID"; then
    echo "exit_code=0"
else
    echo "exit_code=$?"
fi
CHECK_PID=""

section "Scenario 5: invalid arguments (expect exit code 2)"
for args in "127.0.0.1 0" "127.0.0.1 8000 -n 0" "127.0.0.1 abc" "127.0.0.1 8000 -o /tmp/does-not-exist/results.csv"; do
    # shellcheck disable=SC2086
    python3 tcp_check.py $args >/dev/null 2>&1
    echo "args='$args' exit_code=$?"
done

section "Generated CSV files"
ls -1 "$OUT_DIR"/*.csv
