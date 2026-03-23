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
KEY_BODY=$(echo "$PUB_KEY" | awk '{print $2}')
MACHINE=$(hostname)
DATE=$(date +%Y%m%d)

# ── Auth key ──────────────────────────────────────────────────────────────────
echo "Checking GitHub auth key..."
EXISTING_AUTH=$(gh api user/keys --jq '.[].key' 2>/dev/null || echo "")

if echo "$EXISTING_AUTH" | grep -qF "$KEY_BODY"; then
  echo "Auth key already registered, skipping."
else
  echo "Registering auth key with GitHub..."
  gh api user/keys \
    --method POST \
    --field title="${MACHINE}-auth-${DATE}" \
    --field key="$PUB_KEY"
  echo "Auth key registered."
fi

# ── Signing key ───────────────────────────────────────────────────────────────
echo "Checking GitHub signing key..."
EXISTING_SIGNING=$(gh api user/ssh_signing_keys --jq '.[].key' 2>/dev/null || echo "")

if echo "$EXISTING_SIGNING" | grep -qF "$KEY_BODY"; then
  echo "Signing key already registered, skipping."
else
  echo "Registering signing key with GitHub..."
  gh api user/ssh_signing_keys \
    --method POST \
    --field title="${MACHINE}-signing-${DATE}" \
    --field key="$PUB_KEY"
  echo "Signing key registered."
fi
