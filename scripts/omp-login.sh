#!/usr/bin/env bash
# Log omp into every provider it can reach from this machine.
#
#   scripts/omp-login.sh          # status + log into anything missing
#
# - API-key providers (DeepSeek, Tavily, ...) need no omp login: omp reads them
#   from env, and roles/shell_ai exports them from Bitwarden into the shell.
#   This script only reports whether they resolve.
# - OAuth providers (Claude Max, Codex Pro, Antigravity) need a one-time browser
#   approval. They are stored in ~/.omp/agent/agent.db and refresh on their own,
#   so this only prompts for the ones that are missing.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OAUTH_PROVIDERS=(anthropic openai-codex google-antigravity)

if ! command -v omp >/dev/null 2>&1; then
  echo "omp not installed — run: just apply-tags omp" >&2
  exit 2
fi

for p in "${OAUTH_PROVIDERS[@]}"; do
  if omp token "$p" >/dev/null 2>&1; then
    printf '  ✓ %s (logged in)\n' "$p"
  else
    printf '  → %s: logging in (approve in browser)\n' "$p"
    omp login "$p" || printf '  ✗ %s login failed\n' "$p"
  fi
done

# API-key providers: resolve via Bitwarden when available.
if session=$("$SCRIPT_DIR/bw-unlock.sh" 2>/dev/null); then
  for item in deepseek-api-key tavily-api-key meta-api-key; do
    if BW_SESSION="$session" bw get item "$item" >/dev/null 2>&1; then
      printf '  ✓ %s (in Bitwarden; exported by shell_ai role)\n' "$item"
    else
      printf '  ⚠ %s not found in Bitwarden\n' "$item"
    fi
  done
else
  echo "  ⚠ Bitwarden locked — skipped API-key providers"
fi
