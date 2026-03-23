#!/usr/bin/env bash
# Shared Bitwarden unlock helper. Source this in run_once_ scripts.
# Usage: source "$HOME/.config/chezmoi/bw-helper.sh" && bw_ensure_unlocked
#
# BW_SESSION forwarding: set SendEnv BW_SESSION in ~/.ssh/config (client) and
# AcceptEnv BW_SESSION in /etc/ssh/sshd_config.d/99-bw-env.conf (server).
# Then unlock once on your main machine and all SSH sessions inherit the session.

bw_ensure_unlocked() {
  # 1. Use session already in environment (e.g. forwarded via SSH)
  if [ -n "${BW_SESSION:-}" ]; then
    if BW_SESSION="$BW_SESSION" bw status 2>/dev/null | grep -q '"status":"unlocked"'; then
      export BW_SESSION
      echo "Bitwarden: using forwarded session."
      return 0
    fi
  fi

  # 2. Use cached session from previous run on this machine
  if [ -f /tmp/bw_session ]; then
    local session
    session=$(cat /tmp/bw_session)
    if BW_SESSION="$session" bw status 2>/dev/null | grep -q '"status":"unlocked"'; then
      export BW_SESSION="$session"
      return 0
    fi
  fi

  # 3. Need to unlock interactively (or login first)
  local status
  status=$(bw status 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "unauthenticated")

  if [ "$status" = "unauthenticated" ]; then
    echo "Bitwarden: not logged in. Running bw login..."
    bw login || return 1
  fi

  echo "Bitwarden: unlocking vault (enter master password)..."
  export BW_SESSION
  BW_SESSION=$(bw unlock --raw)
  echo "$BW_SESSION" > /tmp/bw_session
  chmod 600 /tmp/bw_session
}
