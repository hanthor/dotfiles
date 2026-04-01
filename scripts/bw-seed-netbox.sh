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
  if bw get item "$name" --session "$BW_SESSION" &>/dev/null; then
    echo "  [skip] '$name' already exists"
  else
    bw get template item --session "$BW_SESSION" \
      | jq --arg n "$name" --arg p "$value" \
          '.type=1 | .name=$n | .login.password=$p | .login.username=""' \
      | bw encode \
      | bw create item --session "$BW_SESSION" > /dev/null
    echo "  [created] $name"
  fi
}

DB_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
SECRET_KEY=$(python3 -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters+string.digits+'!@#\$%^&*') for _ in range(50)))")
SU_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
API_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(20))")

echo "Creating NetBox secrets in Bitwarden..."
create_item "netbox-db-password"        "$DB_PASS"
create_item "netbox-secret-key"         "$SECRET_KEY"
create_item "netbox-superuser-password" "$SU_PASS"
create_item "netbox-api-token"          "$API_TOKEN"

echo ""
echo "Done. NetBox superuser login: admin / $SU_PASS"
echo "Store that password somewhere — it won't be shown again."
