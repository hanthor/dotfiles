#!/usr/bin/env bash
# Seed Bitwarden with the omp auth-broker bearer token. Run on the broker host
# (punjab), where `omp auth-broker token` reads the broker's own token.
# Usage: ./scripts/bw-seed-omp-broker.sh
# Re-run safely — updates the existing item in place. `omp auth-broker token`
# prints the current token and does not rotate it. Clients fetch the item with
# `just apply-tags omp`.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/bw-item.sh"

if [ -z "${BW_SESSION:-}" ]; then
  # Assign then export: `export X=$(cmd)` would mask a failed unlock from set -e.
  BW_SESSION=$("$SCRIPT_DIR/bw-unlock.sh")
  export BW_SESSION
fi

NAME="${OMP_AUTH_BROKER_BW_ITEM:-omp-auth-broker-token}"

token=$(omp auth-broker token)
if [ -z "$token" ]; then
  echo "no token from 'omp auth-broker token' — is this the broker host?" >&2
  exit 1
fi

# type 1 = login; the role reads it with `bw get password`.
payload=$(bw get template item \
  | jq --arg name "$NAME" --arg tok "$token" '
      . + {
        name: $name,
        type: 1,
        notes: "Bearer token for the omp auth-broker on punjab. Managed by scripts/bw-seed-omp-broker.sh.",
        login: {username: "omp-auth-broker", password: $tok}
      }')

bw_upsert_item "$NAME" "$payload" 1
bw sync >/dev/null
echo "Done. Run \`just apply-tags omp\` on other machines to pick up the token."
