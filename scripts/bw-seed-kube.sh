#!/usr/bin/env bash
# Seed Bitwarden with kubeconfig + talosconfig from this machine.
# Usage: ./scripts/bw-seed-kube.sh
# Re-run safely — updates existing items in place.
set -euo pipefail

if [ -z "${BW_SESSION:-}" ]; then
  if [ -f /tmp/bw_session ]; then
    export BW_SESSION=$(cat /tmp/bw_session)
  else
    echo "Unlocking Bitwarden..."
    export BW_SESSION=$(bw unlock --raw)
    (umask 077 && printf '%s' "$BW_SESSION" > /tmp/bw_session)
  fi
fi

KUBECONFIG_PATH="${KUBECONFIG:-$HOME/.kube/config}"
TALOSCONFIG_PATH="${TALOSCONFIG:-$HOME/.talos/config}"

seed() {
  local name="$1" path="$2"
  if [ ! -f "$path" ]; then
    echo "skip $name — $path does not exist"
    return 0
  fi

  local notes
  notes=$(cat "$path")
  local existing_id
  existing_id=$(bw list items --search "$name" 2>/dev/null \
    | jq -r --arg name "$name" '.[] | select(.name == $name) | .id' \
    | head -n1)

  local payload
  payload=$(bw get template item \
    | jq --arg name "$name" --arg notes "$notes" \
        '. + {name: $name, notes: $notes, type: 2, secureNote: {type: 0}, login: null}')

  if [ -n "$existing_id" ]; then
    echo "updating $name ($existing_id)"
    echo "$payload" | bw encode | bw edit item "$existing_id" >/dev/null
  else
    echo "creating $name"
    echo "$payload" | bw encode | bw create item >/dev/null
  fi
}

seed kubeconfig "$KUBECONFIG_PATH"
seed talosconfig "$TALOSCONFIG_PATH"
bw sync >/dev/null
echo "Done. Run \`just apply-tags kube\` on other machines to fetch."
