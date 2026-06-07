#!/usr/bin/env bash
# Resolve a usable BW_SESSION on the local machine and print it on stdout.
#
# Tier order: BW_SESSION env → /tmp/bw_session → interactive `bw unlock`.
# Successful unlock is cached to /tmp/bw_session (0600) for reuse within and
# across runs.
#
# Exit codes:
#   0 — session printed to stdout (use it)
#   2 — bw CLI not installed
#   3 — vault is unauthenticated (needs `bw login` first)
#   4 — interactive unlock failed
#
# The bitwarden role reads /tmp/bw_session directly, so callers don't need to
# do anything with the cached file — just `export BW_SESSION=$(scripts/bw-unlock.sh)`.

set -euo pipefail

cache=/tmp/bw_session

if [ -n "${BW_SESSION:-}" ]; then
  printf '%s' "$BW_SESSION"
  exit 0
fi

if [ -s "$cache" ]; then
  cat "$cache"
  exit 0
fi

if ! command -v bw >/dev/null 2>&1; then
  echo "bw CLI not installed on $(hostname)" >&2
  exit 2
fi

status=$(bw status 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo unknown)
if [ "$status" = "unauthenticated" ]; then
  echo "Bitwarden not logged in on $(hostname). Run 'bw login' first." >&2
  exit 3
fi

echo "Unlocking Bitwarden..." >&2
if ! session=$(bw unlock --raw 2>/dev/null); then
  echo "Bitwarden unlock failed." >&2
  exit 4
fi

(umask 077 && printf '%s' "$session" > "$cache")
printf '%s' "$session"
