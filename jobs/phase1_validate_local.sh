#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/navneeth-arun04/GridMind"
MASTER="$ROOT/master-daemon-rework.py"
WORKER="$ROOT/worker-listener-daemon.py"
SMOKE="$ROOT/jobs/phase1_smoke_test.py"

export GRIDMIND_MASTER_IP=127.0.0.1
export GRIDMIND_MASTER_PORT=5577
export GRIDMIND_WORKER_COMMAND_PORT=5556
export GRIDMIND_AUTO_ONBOARD=true
export GRIDMIND_SHARED_SECRET=gridmind-dev-secret

echo "[1/5] Cleaning old local test processes..."
pkill -f "master-daemon-rework.py" || true
pkill -f "worker-listener-daemon.py" || true
sleep 1

echo "[2/5] Starting master daemon..."
python3 "$MASTER" > "$ROOT/logs/phase1_master_local.log" 2>&1 &
MASTER_PID=$!

sleep 2

echo "[3/5] Starting worker daemon..."
python3 "$WORKER" > "$ROOT/logs/phase1_worker_local.log" 2>&1 &
WORKER_PID=$!

sleep 5

echo "[4/5] Running smoke test..."
python3 "$SMOKE" --master "http://127.0.0.1:5577" --secret "$GRIDMIND_SHARED_SECRET"

echo "[5/5] Done. Stopping local daemons..."
kill "$WORKER_PID" || true
kill "$MASTER_PID" || true

echo "Phase-1 local validation PASSED"
