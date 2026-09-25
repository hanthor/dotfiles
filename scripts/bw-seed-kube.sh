#!/usr/bin/env bash
# Seed Bitwarden with kubeconfig + talosconfig from this machine.
# Usage: ./scripts/bw-seed-kube.sh
# Re-run safely — updates existing items in place.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/bw-item.sh"

if [ -z "${BW_SESSION:-}" ]; then
  export BW_SESSION=$("$SCRIPT_DIR/bw-unlock.sh")
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
  local payload
  payload=$(bw get template item \
    | jq --arg name "$name" --arg notes "$notes" \
        '. + {name: $name, notes: $notes, type: 2, secureNote: {type: 0}, login: null}')

  bw_upsert_item "$name" "$payload"
}

seed kubeconfig "$KUBECONFIG_PATH"
seed talosconfig "$TALOSCONFIG_PATH"
bw sync >/dev/null
echo "Done. Run \`just apply-tags kube\` on other machines to fetch."
