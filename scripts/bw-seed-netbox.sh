#!/usr/bin/env bash
# Creates NetBox secrets in Bitwarden.
# Usage: BW_SESSION=$(bw unlock --raw) bash scripts/bw-seed-netbox.sh
set -euo pipefail

export PATH="/home/linuxbrew/.linuxbrew/bin:$PATH"

if [ -z "${BW_SESSION:-}" ]; then
  echo "BW_SESSION is not set. Run: export BW_SESSION=\$(bw unlock --raw)"
  exit 1
fi

create_item() {
  local name="$1" value="$2"
  local uris='[{"uri":"https://bihar.manatee-basking.ts.net/netbox"},{"uri":"https://bihar.manatee-basking.ts.net/auth"}]'
  local existing
  
  if existing=$(bw get item "$name" --session "$BW_SESSION" 2>/dev/null); then
    echo "  [updating] '$name' with URIs..."
    echo "$existing" \
      | jq --argjson u "$uris" '.login.uris=$u | .login.username="admin"' \
      | bw encode \
      | bw edit item "$(echo "$existing" | jq -r .id)" --session "$BW_SESSION" > /dev/null
  else
    bw get template item --session "$BW_SESSION" \
      | jq --arg n "$name" --arg p "$value" --argjson u "$uris" \
          '.type=1 | .name=$n | .login.password=$p | .login.username="admin" | .login.uris=$u' \
      | bw encode \
      | bw create item --session "$BW_SESSION" > /dev/null
    echo "  [created] $name"
  fi
}

DB_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
SECRET_KEY=$(python3 -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters+string.digits+'!@#\$%^&*') for _ in range(50)))")
SU_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
API_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(20))")
OIDC_CLIENT_ID=$(python3 -c "import secrets; print(secrets.token_hex(16))")
OIDC_CLIENT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

echo "Creating NetBox secrets in Bitwarden..."
create_item "netbox-db-password"        "$DB_PASS"
create_item "netbox-secret-key"         "$SECRET_KEY"
create_item "netbox-superuser-password" "$SU_PASS"
create_item "netbox-api-token"          "$API_TOKEN"
create_item "netbox-oidc-client-id"     "$OIDC_CLIENT_ID"
create_item "netbox-oidc-client-secret" "$OIDC_CLIENT_SECRET"

echo ""
echo "Done. NetBox superuser login: admin / $SU_PASS"
echo "Store that password somewhere — it won't be shown again."
