#!/usr/bin/env bash
set -euo pipefail

eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"

# Determine the signing key path from gitconfig
SIGNING_KEY_PATH=$(git config --global user.signingkey)
if [ -z "$SIGNING_KEY_PATH" ]; then
  echo "ERROR: user.signingkey not set in gitconfig."
  exit 1
fi

# Expand ~ in path
SIGNING_KEY_PATH="${SIGNING_KEY_PATH/#\~/$HOME}"

if [ ! -f "$SIGNING_KEY_PATH" ]; then
  echo "ERROR: Signing key not found at $SIGNING_KEY_PATH — run SSH keys script first."
  exit 1
fi

PUB_KEY=$(cat "$SIGNING_KEY_PATH")
KEY_TITLE="$(hostname)-signing-$(date +%Y%m%d)"

echo "Checking if signing key is already registered with GitHub..."

# Fetch existing signing keys and check if this public key is already present
EXISTING=$(gh api user/ssh_signing_keys --jq '.[].key' 2>/dev/null || echo "")

if echo "$EXISTING" | grep -qF "$(echo "$PUB_KEY" | awk '{print $2}')"; then
  echo "Signing key already registered, skipping."
  exit 0
fi

echo "Registering signing key with GitHub..."
gh api user/ssh_signing_keys \
  --method POST \
  --field title="$KEY_TITLE" \
  --field key="$PUB_KEY"

echo "Signing key registered."
