#!/usr/bin/env bash
set -euo pipefail

# Layer-2 adversarial checks for GridMind Zero Trust.
# Run while master daemon is active. Worker id can be exported or passed.
# Usage:
#   WORKER_ID=<id> ./jobs/phase2_layer2_zero_trust_checks.sh

MASTER_IP="${GRIDMIND_MASTER_IP:-192.168.0.10}"
MASTER_PORT="${GRIDMIND_MASTER_PORT:-5577}"
BASE="http://${MASTER_IP}:${MASTER_PORT}"
WORKER_ID="${WORKER_ID:-}"

if [[ -z "${WORKER_ID}" ]]; then
  echo "WORKER_ID is required" >&2
  exit 1
fi

echo "[1/4] Replay check (same message_id twice)"
MSG_ID="replay-test-$(date +%s)"
TS="$(date -Iseconds)"
PAYLOAD1="{\"worker_id\":\"${WORKER_ID}\",\"timestamp\":\"${TS}\",\"message_id\":\"${MSG_ID}\",\"checksum\":\"bogus\"}"
curl -sS -X POST "${BASE}/api/worker/token/refresh" -H 'Content-Type: application/json' -d "${PAYLOAD1}" | cat
curl -sS -X POST "${BASE}/api/worker/token/refresh" -H 'Content-Type: application/json' -d "${PAYLOAD1}" | cat

echo "[2/4] Tampered checksum check"
BAD="{\"worker_id\":\"${WORKER_ID}\",\"timestamp\":\"${TS}\",\"message_id\":\"tamper-$(date +%s)\",\"auth_token\":\"bad\",\"checksum\":\"bad\"}"
curl -sS -X POST "${BASE}/api/worker/heartbeat" -H 'Content-Type: application/json' -d "${BAD}" | cat

echo "[3/4] Quarantine/unquarantine control check"
curl -sS -X POST "${BASE}/api/master/worker/disconnect" -H 'Content-Type: application/json' -d "{\"worker_id\":\"${WORKER_ID}\"}" | cat
curl -sS -X POST "${BASE}/api/master/worker/unquarantine" -H 'Content-Type: application/json' -d "{\"worker_id\":\"${WORKER_ID}\",\"force\":true,\"note\":\"layer2-script\"}" | cat

echo "[4/4] Overview snapshot"
curl -sS "${BASE}/api/master/overview" | cat

echo "Layer-2 checks completed"
