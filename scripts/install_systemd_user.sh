#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}"
STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
SYSTEMD_DIR="${HOME}/.config/systemd/user"
PYTHON="${PYTHON:-python3}"

mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/afterglow-ingest.service" <<EOF
[Unit]
Description=Afterglow fallback ingestion daemon

[Service]
Type=simple
Environment=OPENCLAW_WORKSPACE=$WORKSPACE
Environment=OPENCLAW_STATE_DIR=$STATE_DIR
WorkingDirectory=$WORKSPACE
ExecStart=$PYTHON $WORKSPACE/scripts/afterglow_daemon.py --interval 5
Restart=always
RestartSec=5
EOF

cat > "$SYSTEMD_DIR/afterglow-pulse.service" <<EOF
[Unit]
Description=Afterglow autonomous pulse

[Service]
Type=oneshot
Environment=OPENCLAW_WORKSPACE=$WORKSPACE
Environment=OPENCLAW_STATE_DIR=$STATE_DIR
WorkingDirectory=$WORKSPACE
ExecStart=$PYTHON $WORKSPACE/scripts/pulse.py --once
EOF

cat > "$SYSTEMD_DIR/afterglow-pulse.timer" <<EOF
[Unit]
Description=Run Afterglow pulse periodically

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
AccuracySec=1min
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now afterglow-ingest.service
systemctl --user enable --now afterglow-pulse.timer

echo "Installed and started user services:"
echo "  afterglow-ingest.service"
echo "  afterglow-pulse.timer"
