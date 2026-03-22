#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "FAIL: usage tools/watch_krax_completion.sh <job_id> [timeout_seconds]"
  exit 2
fi

KRAX_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JOB_ID="$1"
TIMEOUT="${2:-300}"
SLEEP_SEC=2

elapsed=0
while (( elapsed <= TIMEOUT )); do
  for candidate in \
    "$KRAX_ROOT/runs/$JOB_ID/grok.txt" \
    "$KRAX_ROOT/archive/$JOB_ID/grok.txt" \
    "$KRAX_ROOT/runs/$JOB_ID/response.txt" \
    "$KRAX_ROOT/archive/$JOB_ID/response.txt"; do
    if [[ -f "$candidate" ]]; then
      echo "PASS: job=$JOB_ID output=$candidate"
      exit 0
    fi
  done

  if [[ -f "$KRAX_ROOT/failed/$JOB_ID/rejection.json" ]]; then
    echo "FAIL: job=$JOB_ID rejected"
    exit 1
  fi

  sleep "$SLEEP_SEC"
  elapsed=$((elapsed + SLEEP_SEC))
done

echo "FAIL: job=$JOB_ID timeout=${TIMEOUT}s"
exit 1
