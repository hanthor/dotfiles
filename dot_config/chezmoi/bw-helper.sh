#!/usr/bin/env bash
# Shared Bitwarden unlock helper. Source this in run_once_ scripts.
# Usage: source "$HOME/.config/chezmoi/bw-helper.sh" && bw_ensure_unlocked

bw_ensure_unlocked() {
  # Check if existing session is still valid
  if [ -f /tmp/bw_session ]; then
    local session
    session=$(cat /tmp/bw_session)
    if BW_SESSION="$session" bw status 2>/dev/null | grep -q '"status":"unlocked"'; then
      export BW_SESSION="$session"
      return 0
    fi
  fi

  # Need to unlock (or login first if not logged in)
  local status
  status=$(bw status 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "unauthenticated")

  if [ "$status" = "unauthenticated" ]; then
    echo "Bitwarden: not logged in. Running bw login..."
    bw login
  fi

  echo "Bitwarden: unlocking vault..."
  export BW_SESSION
  BW_SESSION=$(bw unlock --raw)
  echo "$BW_SESSION" > /tmp/bw_session
  chmod 600 /tmp/bw_session
}
