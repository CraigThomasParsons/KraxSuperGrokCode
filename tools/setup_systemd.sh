#!/bin/bash
# Piper Systemd Setup Script
# Installs the Piper server as a user systemd service

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPER_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Piper Systemd Setup ==="

# Create user systemd directory if it doesn't exist
mkdir -p ~/.config/systemd/user

# Copy service file
cp "$PIPER_ROOT/systemd/piper-server.service" ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

echo "[*] Service installed. Usage:"
echo ""
echo "  Start:   systemctl --user start piper-server"
echo "  Stop:    systemctl --user stop piper-server"
echo "  Status:  systemctl --user status piper-server"
echo "  Logs:    journalctl --user -u piper-server -f"
echo "  Enable:  systemctl --user enable piper-server  (start on login)"
echo ""
