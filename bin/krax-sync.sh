#!/usr/bin/env bash
# krax-sync.sh — Cron entry point for Krax project synchronization.
#
# Processes one Bridgit package per invocation via krax_sync_one.py.
# Uses flock to prevent overlapping runs if a previous sync is still active.
# Follows the same pattern as chatprojects-projects-refresh.sh.
#
# Cron entry (every 3 hours at minute 23):
#   23 */3 * * * /home/craigpar/Code/Krax/bin/krax-sync.sh >> /home/craigpar/.cache/krax-sync-cron.log 2>&1

set -euo pipefail

KRAX_ROOT="/home/craigpar/Code/Krax"
PYTHON_BIN="$KRAX_ROOT/venv/bin/python3"
SYNC_SCRIPT="$KRAX_ROOT/bin/krax_sync_one.py"
LOCK_FILE="/home/craigpar/.cache/krax-sync.lock"
STATUS_FILE="/home/craigpar/.cache/krax-sync.status"
LOG_PREFIX="[krax-sync]"

mkdir -p /home/craigpar/.cache

on_error() {
  local exit_code=$?
  printf 'status=error\nexit_code=%s\nlast_run=%s\n' "$exit_code" "$(date -Iseconds)" > "$STATUS_FILE"
  echo "$LOG_PREFIX $(date -Iseconds) sync failed (exit=$exit_code)"
}
trap on_error ERR

# Acquire an exclusive lock — if another krax-sync is still running,
# skip this invocation entirely rather than queuing up.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "$LOG_PREFIX $(date -Iseconds) skipped (another run in progress)"
  exit 0
fi

echo "$LOG_PREFIX $(date -Iseconds) starting sync"
"$PYTHON_BIN" "$SYNC_SCRIPT"

printf 'status=ok\nexit_code=0\nlast_run=%s\n' "$(date -Iseconds)" > "$STATUS_FILE"
echo "$LOG_PREFIX $(date -Iseconds) complete"
