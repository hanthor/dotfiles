#!/usr/bin/env bash
# scripts/bw-seed-ssh-keys.sh
#
# Pulls SSH keys from all machines and seeds them into Bitwarden.
# Run this once before doing chezmoi init on any machine.
#
# Usage:
#   ./scripts/bw-seed-ssh-keys.sh            # all machines
#   ./scripts/bw-seed-ssh-keys.sh karnataka  # single machine
#
# Requirements: bw, ssh, jq (all available via Homebrew)
set -euo pipefail

eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"

# ── Config ────────────────────────────────────────────────────────────────────
LOCAL_MACHINE=$(hostname)

declare -A MACHINE_HOST=(
  [himachal]="himachal"
  [karnataka]="karnataka"
  [dilli]="dilli"
  [kanpur]="kanpur"
  [goa]="goa"
  [bihar]="bihar"
  [matrix]="matrix.reilly.asia"
  [lkofoss]="lkofoss.club"
)

SSH_USER="james"

# ── Bitwarden login/unlock ────────────────────────────────────────────────────
STATUS=$(bw status 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "unauthenticated")

if [ "$STATUS" = "unauthenticated" ]; then
  echo "Bitwarden: logging in..."
  bw login
fi

echo "Bitwarden: unlocking vault..."
export BW_SESSION
BW_SESSION=$(bw unlock --raw)
echo "Bitwarden: unlocked."
echo ""

# ── Helper: upsert a machine's keys into Bitwarden ───────────────────────────
upsert_bw_item() {
  local machine="$1"
  local private_key="$2"
  local public_key="$3"

  # Build the JSON template
  local item_json
  item_json=$(jq -n \
    --arg name "$machine" \
    --arg priv "$private_key" \
    --arg pub  "$public_key" \
    '{
      type: 5,
      name: $name,
      sshKey: {
        privateKey:     $priv,
        publicKey:      $pub,
        keyFingerprint: ""
      }
    }')

  # Check if item already exists (type 5 = SSH Key)
  local existing_id
  existing_id=$(BW_SESSION="$BW_SESSION" bw list items --search "$machine" 2>/dev/null \
    | python3 -c "
import sys, json
items = json.load(sys.stdin)
for i in items:
    if i.get('name') == '$machine' and i.get('type') == 5:
        print(i['id'])
        break
" 2>/dev/null || true)

  if [ -n "$existing_id" ]; then
    echo "  → Updating existing Bitwarden item (id: $existing_id)..."
    echo "$item_json" | BW_SESSION="$BW_SESSION" bw encode | BW_SESSION="$BW_SESSION" bw edit item "$existing_id" > /dev/null
    echo "  ✓ Updated."
  else
    echo "  → Creating new Bitwarden item..."
    echo "$item_json" | BW_SESSION="$BW_SESSION" bw encode | BW_SESSION="$BW_SESSION" bw create item > /dev/null
    echo "  ✓ Created."
  fi
}

# ── Helper: register public key with GitHub (auth + signing) ─────────────────
register_github_key() {
  local machine="$1"
  local public_key="$2"
  local key_body
  key_body=$(echo "$public_key" | awk '{print $2}')

  # Auth key
  local existing_auth
  existing_auth=$(gh api user/keys --jq '.[].key' 2>/dev/null || true)
  if echo "$existing_auth" | grep -qF "$key_body"; then
    echo "  ✓ GitHub auth key already registered."
  else
    gh api user/keys --method POST \
      --field title="${machine}-auth" \
      --field key="$public_key" > /dev/null
    echo "  ✓ GitHub auth key registered."
  fi

  # Signing key
  local existing_signing
  existing_signing=$(gh api user/ssh_signing_keys --jq '.[].key' 2>/dev/null || true)
  if echo "$existing_signing" | grep -qF "$key_body"; then
    echo "  ✓ GitHub signing key already registered."
  else
    gh api user/ssh_signing_keys --method POST \
      --field title="${machine}-signing" \
      --field key="$public_key" > /dev/null
    echo "  ✓ GitHub signing key registered."
  fi
}

# ── Helper: get keys from a machine ──────────────────────────────────────────
fetch_keys() {
  local machine="$1"
  local host="${MACHINE_HOST[$machine]}"

  echo "── $machine ($host) ──"

  local private_key=""
  local public_key=""

  if [ "$machine" = "$LOCAL_MACHINE" ]; then
    # Read locally — try machine-named key first, fall back to default
    local priv_path="$HOME/.ssh/${machine}_id_ed25519"
    [ ! -f "$priv_path" ] && priv_path="$HOME/.ssh/id_ed25519"

    if [ ! -f "$priv_path" ]; then
      echo "  ✗ No SSH key found at ~/.ssh/${machine}_id_ed25519 or ~/.ssh/id_ed25519 — skipping."
      return
    fi

    private_key=$(cat "$priv_path")
    public_key=$(cat "${priv_path}.pub")
  else
    # Fetch remotely via SSH
    local ssh_opts=(-o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new -o BatchMode=yes)
    local remote_cmd='
      priv="$HOME/.ssh/'"$machine"'_id_ed25519"
      [ ! -f "$priv" ] && priv="$HOME/.ssh/id_ed25519"
      if [ ! -f "$priv" ]; then echo "NOKEY"; exit 0; fi
      echo "PRIVKEY_START"
      cat "$priv"
      echo "PRIVKEY_END"
      echo "PUBKEY_START"
      cat "${priv}.pub"
      echo "PUBKEY_END"
    '

    local output
    if ! output=$(ssh "${ssh_opts[@]}" "${SSH_USER}@${host}" "$remote_cmd" 2>/dev/null); then
      echo "  ✗ SSH unreachable — skipping."
      return
    fi

    if echo "$output" | grep -q "NOKEY"; then
      echo "  ✗ No SSH key found on remote machine — skipping."
      return
    fi

    private_key=$(echo "$output" | sed -n '/PRIVKEY_START/,/PRIVKEY_END/p' | grep -v "PRIVKEY_")
    public_key=$(echo "$output"  | sed -n '/PUBKEY_START/,/PUBKEY_END/p'   | grep -v "PUBKEY_")
  fi

  if [ -z "$private_key" ] || [ -z "$public_key" ]; then
    echo "  ✗ Could not read keys — skipping."
    return
  fi

  echo "  ✓ Keys fetched (pub: $(echo "$public_key" | awk '{print substr($2,1,20)}')...)"
  upsert_bw_item "$machine" "$private_key" "$public_key"
  register_github_key "$machine" "$public_key"
}

# ── Main ──────────────────────────────────────────────────────────────────────
if [ $# -gt 0 ]; then
  # Single machine mode
  for machine in "$@"; do
    if [ -z "${MACHINE_HOST[$machine]+x}" ]; then
      echo "Unknown machine: $machine"
      echo "Valid machines: ${!MACHINE_HOST[*]}"
      exit 1
    fi
    fetch_keys "$machine"
  done
else
  # All machines
  for machine in "${!MACHINE_HOST[@]}"; do
    fetch_keys "$machine"
    echo ""
  done
fi

echo ""
echo "Done. Sync Bitwarden on other devices: bw sync"
