#!/usr/bin/env bash
set -euo pipefail

# Enable chezmoi auto-update timer
if ! systemctl --user is-enabled chezmoi-update.timer &>/dev/null; then
  echo "Enabling chezmoi-update.timer..."
  systemctl --user enable --now chezmoi-update.timer
else
  systemctl --user daemon-reload
  systemctl --user restart chezmoi-update.timer
fi

# Enable syncthing (brew installs it via run_onchange_02, so it's available by now)
if command -v syncthing &>/dev/null || [[ -f /home/linuxbrew/.linuxbrew/bin/syncthing ]]; then
  echo "Enabling syncthing.service..."
  systemctl --user daemon-reload
  systemctl --user enable --now syncthing.service
else
  echo "WARNING: syncthing not found — run 'brew install syncthing' then 'systemctl --user enable --now syncthing.service'"
fi

echo "User services configured."
