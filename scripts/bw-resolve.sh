#!/usr/bin/env bash
# Resolve a usable BW_SESSION. Three modes:
#
#   scripts/bw-resolve.sh local
#     Prints "export BW_SESSION=..." to stdout (for eval) or nothing + exit 1.
#     Uses the bw-unlock.sh chain: env → /tmp/bw_session → interactive unlock.
#
#   scripts/bw-resolve.sh remote <host>
#     SSH to <host>, ensure BW is logged in + unlocked, print the remote session.
#     Tries: API key login (if unauthenticated) → non-interactive unlock
#     (master password from local vault) → interactive unlock.
#     Prints just the session token on stdout (no export prefix).
#
#   scripts/bw-resolve.sh (no args) → alias for "local"
#
# Exit codes:
#   0 — session resolved
#   1 — no session available (caller should skip secrets)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mode="${1:-local}"

# ── local mode ──────────────────────────────────────────────────────────
if [ "$mode" = "local" ]; then
  if session=$("$SCRIPT_DIR/bw-unlock.sh" 2>/dev/null); then
    printf 'export BW_SESSION=%s\n' "$session"
    exit 0
  fi
  exit 1
fi

# ── remote mode ─────────────────────────────────────────────────────────
if [ "$mode" = "remote" ]; then
  host="${2:-}"
  if [ -z "$host" ]; then
    echo "remote mode requires a hostname argument" >&2
    exit 1
  fi

  # Check remote BW auth state
  remote_status=$(ssh "$host" '/home/linuxbrew/.linuxbrew/bin/bw status 2>/dev/null || echo "{}"')
  if echo "$remote_status" | grep -q '"unauthenticated"'; then
    echo "Bitwarden not logged in on $host. Attempting API key login..." >&2
    # Get local BW session for API key lookup
    local_session=$("$SCRIPT_DIR/bw-unlock.sh" 2>/dev/null || true)
    if [ -n "$local_session" ]; then
      BW_CLIENTID=$(bw get username bw-api-key --session "$local_session" 2>/dev/null || true)
      BW_CLIENTSECRET=$(bw get password bw-api-key --session "$local_session" 2>/dev/null || true)
      if [ -n "$BW_CLIENTID" ] && [ -n "$BW_CLIENTSECRET" ]; then
        ssh "$host" "
          export PATH='/home/linuxbrew/.linuxbrew/bin:\$PATH'
          export BW_CLIENTID='${BW_CLIENTID}'
          export BW_CLIENTSECRET='${BW_CLIENTSECRET}'
          bw login --apikey 2>&1 || true
        "
        echo "BW login done on $host." >&2
      else
        echo "WARNING: No 'bw-api-key' item in vault. Run 'bw login' on $host manually." >&2
      fi
    fi
  fi

  # Try to unlock BW on the remote
  remote_session=""
  if echo "$remote_status" | grep -qE '"locked"|"unauthenticated"'; then
    # Try non-interactive unlock using master password from local vault
    local_session=$("$SCRIPT_DIR/bw-unlock.sh" 2>/dev/null || true)
    if [ -n "$local_session" ]; then
      BW_MASTER_PASS=$(bw get password "James Bitwarden" --session "$local_session" 2>/dev/null || true)
      if [ -n "$BW_MASTER_PASS" ]; then
        echo "Unlocking Bitwarden on $host (non-interactive)..." >&2
        remote_session=$(ssh "$host" \
          "export PATH='/home/linuxbrew/.linuxbrew/bin:\$PATH'; BW_PASSWORD='${BW_MASTER_PASS}' bw unlock --passwordenv BW_PASSWORD --raw 2>/dev/null" \
          | tr -d '\r\n')
        if [ -z "$remote_session" ]; then
          remote_session=$(ssh "$host" \
            "export PATH='/home/linuxbrew/.linuxbrew/bin:\$PATH'; bw unlock --raw '${BW_MASTER_PASS}' 2>/dev/null" \
            | tr -d '\r\n')
        fi
      fi
    fi
    if [ -z "$remote_session" ]; then
      echo "Unlocking Bitwarden on $host (enter master password when prompted)..." >&2
      remote_session=$(ssh -t "$host" \
        'export PATH="/home/linuxbrew/.linuxbrew/bin:$PATH"; bw unlock --raw 2>/dev/null' \
        | tr -d '\r\n')
    fi
  fi

  if [ -z "$remote_session" ]; then
    echo "WARNING: Could not unlock BW on $host." >&2
    exit 1
  fi

  printf '%s' "$remote_session"
  exit 0
fi

echo "Unknown mode: $mode (use 'local' or 'remote <host>')" >&2
exit 1
