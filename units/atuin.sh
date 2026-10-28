#!/usr/bin/env bash
# atuin unit: log in to atuin sync from Bitwarden and import shell history.
# The config file itself (~/.config/atuin/config.toml) is deployed by chezmoi.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

data="$HOME/.local/share/atuin"
allow_import=1

if ! command -v atuin >/dev/null 2>&1; then
  note "SKIPPED: atuin not installed (brew install atuin)"
  exit 0
fi

if [ "${UNITS_CHECK:-0}" = 1 ]; then
  note "FAIL: atuin login status cannot be inspected safely: atuin status opens and may initialize its SQLite stores"
  exit 1
fi

step "atuin data dir" install -d -m 0700 "$data"
[ "$UNIT_FAILED" = 0 ] || finish

logged_in() {
  atuin status >/dev/null 2>&1
}

atuin_login() {
  local s item u p k version key_path line local_key info
  s="$(bw_session)"
  if [ -z "$s" ]; then
    note "PARTIAL: atuin not logged in; vault locked (bw unlock, then just apply-tags atuin)"
    return 0
  fi
  item="$(BW_SESSION="$s" bw get item atuin.sh 2>/dev/null)" || item=""
  u="$(printf '%s' "$item" | jq -r '.login.username // empty' 2>/dev/null)"
  p="$(printf '%s' "$item" | jq -r '.login.password // empty' 2>/dev/null)"
  k="$(printf '%s' "$item" | jq -r '.fields[]? | select(.name=="key") | .value' 2>/dev/null | head -n1)"
  if [ -z "$u" ] || [ -z "$p" ] || [ -z "$k" ]; then
    note "PARTIAL: Bitwarden item atuin.sh missing or incomplete; atuin login skipped"
    return 0
  fi
  # Atuin gained non-interactive environment credentials in 18.24. Older
  # versions need a manual login; never expose the password or key in argv.
  version="$(atuin --version 2>/dev/null)"
  if [[ ! "$version" =~ ([0-9]+)\.([0-9]+)\.([0-9]+) ]] ||
    (( 10#${BASH_REMATCH[1]} < 18 ||
       (10#${BASH_REMATCH[1]} == 18 && 10#${BASH_REMATCH[2]} < 24) )); then
    note "PARTIAL: atuin 18.24 or newer required for unattended login; upgrade or run atuin login interactively"
    allow_import=0
    return 0
  fi

  # Let Atuin resolve its configured key path, including the newer data layout.
  key_path=""
  if ! info="$(atuin info 2>/dev/null)"; then
    note "PARTIAL: cannot determine the Atuin key path; inspect the local data and log in interactively"
    allow_import=0
    return 0
  fi
  while IFS= read -r line; do
    case "$line" in 'key path: '*) key_path="${line#key path: }" ;; esac
  done <<< "$info"
  if [ -z "$key_path" ]; then
    note "PARTIAL: cannot determine the Atuin key path; inspect the local data and log in interactively"
    allow_import=0
    return 0
  fi
  if [ -e "$key_path" ] || [ -L "$key_path" ]; then
    local_key="$(atuin key 2>/dev/null)" || {
      note "PARTIAL: cannot read the existing Atuin key; inspect it and log in interactively"
      allow_import=0
      return 0
    }
    if [ "$local_key" != "$k" ]; then
      note "PARTIAL: existing Atuin key differs from the vault; inspect it and log in interactively"
      allow_import=0
      return 0
    fi
  fi
  # Keep both the history and any existing key; Atuin writes a missing key.
  if ! ATUIN_PASSWORD="$p" ATUIN_ENCRYPTION_KEY="$k" atuin login -u "$u" </dev/null; then
    allow_import=0
    return 1
  fi
  soft "atuin sync" atuin sync
}

if ! logged_in; then
  step "atuin login" atuin_login
fi

if [ "$allow_import" = 1 ] && [ ! -e "$data/.history_imported" ]; then
  soft "atuin import" sh -c 'atuin import auto 2>&1 && touch "$1/.history_imported"' sh "$data"
fi
finish
