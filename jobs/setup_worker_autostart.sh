#!/usr/bin/env bash
set -euo pipefail

# One-time setup on WORKER machine.
# After this, no manual worker command is needed on each reconnect.

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run as root: sudo bash jobs/setup_worker_autostart.sh"
  exit 1
fi

TARGET_USER="${SUDO_USER:-${USER:-}}"
if [[ -z "$TARGET_USER" ]]; then
  echo "Could not determine target user. Run with sudo from the worker user's shell."
  exit 1
fi

TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
if [[ -z "$TARGET_HOME" ]]; then
  echo "Could not determine home for user: $TARGET_USER"
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="${1:-$DEFAULT_PROJECT_DIR}"
if [[ ! -f "$PROJECT_DIR/worker-listener-daemon.py" ]]; then
  PROJECT_DIR="$TARGET_HOME/GridMind"
fi

SCRIPT_PATH="$PROJECT_DIR/worker-listener-daemon.py"
ENV_PATH="$PROJECT_DIR/.env"
SERVICE_PATH="/etc/systemd/system/gridmind-worker.service"

if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "Missing worker listener script: $SCRIPT_PATH"
  exit 1
fi

if [[ ! -f "$ENV_PATH" ]]; then
  echo "Warning: .env not found at $ENV_PATH"
  echo "Create it before connecting workers to master."
fi

cat > "$SERVICE_PATH" <<EOF
[Unit]
Description=GridMind Worker Listener (Autostart)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=/usr/bin/env python3 $SCRIPT_PATH
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-$ENV_PATH
StandardOutput=journal
StandardError=journal
SyslogIdentifier=gridmind-worker

# Must run as root for iptables HTTP reroute policy.
User=root

[Install]
WantedBy=multi-user.target
EOF

echo "Installed service: $SERVICE_PATH"
echo "Project directory: $PROJECT_DIR"

systemctl daemon-reload
systemctl enable gridmind-worker.service
systemctl restart gridmind-worker.service

sleep 1
systemctl --no-pager --full status gridmind-worker.service || true

echo
echo "Done. Worker now auto-starts GridMind listener on boot/network."
echo "No per-connection worker command is needed anymore."
