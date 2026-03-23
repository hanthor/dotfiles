#!/usr/bin/env bash
set -euo pipefail

# Enable and start the chezmoi auto-update timer (user-level systemd)
if ! systemctl --user is-enabled chezmoi-update.timer &>/dev/null; then
  echo "Enabling chezmoi-update.timer..."
  systemctl --user enable --now chezmoi-update.timer
  echo "chezmoi-update.timer enabled."
else
  echo "chezmoi-update.timer already enabled, reloading..."
  systemctl --user daemon-reload
  systemctl --user restart chezmoi-update.timer
fi
