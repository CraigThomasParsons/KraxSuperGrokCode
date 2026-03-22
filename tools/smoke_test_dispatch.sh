#!/usr/bin/env bash
set -euo pipefail

AURALIS_ROOT="/home/craigpar/Code/Auralis"
KRAX_ROOT="/home/craigpar/Code/Krax"
AURALIS_INBOX="$AURALIS_ROOT/inbox"
KRAX_RUNS="$KRAX_ROOT/runs"
LOG_DIR="$KRAX_ROOT/logs"

AURALIS_PID=""
KRAX_PID=""

cleanup() {
  if [[ -n "$AURALIS_PID" ]]; then
    kill "$AURALIS_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$KRAX_PID" ]]; then
    kill "$KRAX_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

wait_for_http() {
  local url="$1"
  local label="$2"
  local retries=40

  for _ in $(seq 1 "$retries"); do
    if curl -sS --max-time 1 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done

  echo "FAIL: $label not reachable at $url" >&2
  return 1
}

start_if_needed() {
  local url="$1"
  local label="$2"
  local cmd="$3"
  local log_file="$4"
  local __pid_var="$5"

  if curl -sS --max-time 1 "$url" >/dev/null 2>&1; then
    echo "INFO: $label already running"
    return 0
  fi

  echo "INFO: starting $label"
  bash -lc "$cmd" >"$log_file" 2>&1 &
  local pid=$!
  printf -v "$__pid_var" '%s' "$pid"

  wait_for_http "$url" "$label"
}

mkdir -p "$AURALIS_INBOX" "$KRAX_RUNS" "$LOG_DIR"

AURALIS_LOG="$LOG_DIR/auralis_smoke_$$.log"
KRAX_LOG="$LOG_DIR/krax_smoke_$$.log"

start_if_needed "http://localhost:3000/job" "Auralis server" "cd '$AURALIS_ROOT' && python3 bin/auralis_server.py" "$AURALIS_LOG" AURALIS_PID
start_if_needed "http://localhost:3001/job" "Krax server" "cd '$KRAX_ROOT' && python3 bin/krax_server.py" "$KRAX_LOG" KRAX_PID

TEST_JOB="test_dispatch_$(date +%s)_$RANDOM"
TEST_DIR="$AURALIS_INBOX/$TEST_JOB"
mkdir -p "$TEST_DIR"

cat >"$TEST_DIR/briefing.md" <<'EOF'
Create a tiny implementation artifact for smoke-test dispatch.
EOF

cat >"$TEST_DIR/context.md" <<'EOF'
This is an automated smoke test for Auralis -> Krax handoff.
EOF

# Prime Auralis with the queued job and verify it is discoverable.
JOB_PAYLOAD=$(curl -sS "http://localhost:3000/job")
if [[ "$JOB_PAYLOAD" != *"\"id\": \"$TEST_JOB\""* ]]; then
  echo "FAIL: Auralis did not return expected job id $TEST_JOB" >&2
  echo "DEBUG: payload=$JOB_PAYLOAD" >&2
  exit 1
fi

touch "$LOG_DIR/krax_receipt_marker_$$"
MARKER="$LOG_DIR/krax_receipt_marker_$$"

# Simulate extension completion callback to trigger Auralis -> Krax dispatch.
COMPLETE_PAYLOAD=$(cat <<EOF
{"id":"$TEST_JOB","response":"Smoke dispatch response body.","debug":"smoke_test_dispatch"}
EOF
)

curl -sS -X POST "http://localhost:3000/job/complete" \
  -H "Content-Type: application/json" \
  -d "$COMPLETE_PAYLOAD" >/dev/null

RECEIPT_PATH=""
for _ in $(seq 1 60); do
  RECEIPT_PATH=$(find "$KRAX_RUNS" -mindepth 2 -maxdepth 2 -name receipt.json -newer "$MARKER" | head -n 1 || true)
  if [[ -n "$RECEIPT_PATH" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$RECEIPT_PATH" ]]; then
  echo "FAIL: no new receipt.json found within 60 seconds" >&2
  echo "INFO: Auralis log: $AURALIS_LOG" >&2
  echo "INFO: Krax log: $KRAX_LOG" >&2
  exit 1
fi

if ! grep -q '"status"[[:space:]]*:[[:space:]]*"received"' "$RECEIPT_PATH"; then
  echo "FAIL: receipt exists but status is not received" >&2
  cat "$RECEIPT_PATH" >&2
  exit 1
fi

echo "PASS: dispatch smoke test succeeded"
echo "INFO: receipt=$RECEIPT_PATH"
