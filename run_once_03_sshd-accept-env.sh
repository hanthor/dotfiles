#!/usr/bin/env bash
# Allow BW_SESSION to be forwarded into SSH sessions on this machine.
# Client side: SendEnv BW_SESSION in ~/.ssh/config (managed by chezmoi).
# Server side: this script adds AcceptEnv BW_SESSION via a sshd drop-in.
set -euo pipefail

DROPIN_DIR="/etc/ssh/sshd_config.d"
DROPIN_FILE="$DROPIN_DIR/99-bw-env.conf"

if [ ! -d "$DROPIN_DIR" ]; then
  echo "sshd_config.d not found — skipping (sshd may not support drop-ins)"
  exit 0
fi

if grep -qF "AcceptEnv BW_SESSION" "$DROPIN_FILE" 2>/dev/null; then
  echo "sshd already accepts BW_SESSION, skipping."
  exit 0
fi

echo "AcceptEnv BW_SESSION" | sudo tee "$DROPIN_FILE" > /dev/null
echo "Added AcceptEnv BW_SESSION to $DROPIN_FILE"

# Reload sshd if running
if systemctl is-active --quiet sshd 2>/dev/null; then
  sudo systemctl reload sshd && echo "sshd reloaded."
elif systemctl is-active --quiet ssh 2>/dev/null; then
  sudo systemctl reload ssh && echo "ssh reloaded."
fi
