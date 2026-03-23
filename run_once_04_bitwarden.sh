#!/usr/bin/env bash
set -euo pipefail

eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
source "$HOME/.config/chezmoi/bw-helper.sh"

# Ensure bw is installed
if ! command -v bw &>/dev/null; then
  echo "ERROR: bitwarden-cli (bw) not found. Run packages script first."
  exit 1
fi

# Login if unauthenticated (truly once per machine — bw remembers auth)
STATUS=$(bw status 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "unauthenticated")

if [ "$STATUS" = "unauthenticated" ]; then
  echo "Bitwarden: first-time login required."
  echo "Tip: enable 'Login with Device' in the Bitwarden mobile app to approve from your phone."
  bw login || { echo "ERROR: bw login failed"; exit 1; }
  echo "Bitwarden: login complete."
else
  echo "Bitwarden: already logged in."
fi

# Unlock and cache session
bw_ensure_unlocked
echo "Bitwarden: vault unlocked."
