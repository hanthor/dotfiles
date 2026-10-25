#!/usr/bin/env bash
# Store the Tailscale OAuth client secret in Bitwarden item `tailscale-apikey`.
# Used by the tailscale role (as the join auth key) and scripts/tailnet.py (device gc/rename).
#
# Create the client first: https://login.tailscale.com/admin/settings/oauth
#   scopes: devices:core (write), auth_keys (write); tag: tag:fleet
# Usage: ./scripts/bw-seed-tailnet.sh            (prompts for the secret, no echo)
#        printf %s "$SECRET" | ./scripts/bw-seed-tailnet.sh
# The secret is checked against Tailscale before anything is written.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/bw-item.sh"

if [ -z "${BW_SESSION:-}" ]; then
  BW_SESSION=$("$SCRIPT_DIR/bw-unlock.sh")
  export BW_SESSION
fi

if [ -t 0 ]; then
  read -rs -p "Tailscale OAuth client secret (tskey-client-...): " secret; echo >&2
else
  secret=$(cat)
fi
secret="${secret//[[:space:]]/}"
case "$secret" in
  tskey-client-*) ;;
  *) echo "that is not an OAuth client secret (expected tskey-client-...)" >&2; exit 1 ;;
esac
cid=$(cut -d- -f3 <<<"$secret")

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST https://api.tailscale.com/api/v2/oauth/token \
  --data-urlencode "client_id=$cid" --data-urlencode "client_secret=$secret")
if [ "$code" != 200 ]; then
  echo "Tailscale rejected the secret (HTTP $code); nothing written." >&2
  exit 1
fi

payload=$(bw get template item \
  | jq --arg tok "$secret" --arg cid "$cid" '
      . + {
        name: "tailscale-apikey",
        type: 1,
        notes: "Tailscale OAuth client (devices:core, auth_keys; tag:fleet). Used as the join auth key by the tailscale role and by scripts/tailnet.py. Managed by scripts/bw-seed-tailnet.sh.",
        login: {username: $cid, password: $tok}
      }')

bw_upsert_item "tailscale-apikey" "$payload" 1
bw sync >/dev/null
echo "Done. Check the tailnet with: just tailnet-audit"
