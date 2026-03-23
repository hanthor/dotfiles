#!/usr/bin/env bash
set -euo pipefail

eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
source "$HOME/.config/chezmoi/bw-helper.sh"
bw_ensure_unlocked

# Check if already authenticated
if gh auth status &>/dev/null; then
  echo "gh: already authenticated, skipping login."
else
  echo "Fetching GitHub token from Bitwarden..."
  GITHUB_TOKEN=$(BW_SESSION="$BW_SESSION" bw get password github-token)

  if [ -z "$GITHUB_TOKEN" ]; then
    echo "ERROR: Could not fetch github-token from Bitwarden."
    exit 1
  fi

  echo "$GITHUB_TOKEN" | gh auth login --with-token
  echo "gh: authenticated."
fi

# Ensure SSH protocol is set
gh config set git_protocol ssh
echo "gh: git protocol set to SSH."
