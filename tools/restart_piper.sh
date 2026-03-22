#!/bin/bash
# Piper Server Restart Script
# Kills any existing server and starts a new one

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPER_ROOT="$(dirname "$SCRIPT_DIR")"
SERVER_SCRIPT="$PIPER_ROOT/bin/piper_server.py"

echo "=== Piper Server Restart ==="

# Kill any existing piper server processes
echo "[*] Stopping existing server(s)..."
pkill -f "piper_server.py" 2>/dev/null

# Also kill anything on port 3000
fuser -k 3000/tcp 2>/dev/null

# Wait for port to be released
sleep 1

# Start the server
echo "[*] Starting Piper server..."
cd "$PIPER_ROOT"
python3 "$SERVER_SCRIPT"
