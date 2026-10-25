#!/usr/bin/env bash
# atuin unit: log in to atuin sync from Bitwarden and import shell history.
# The config file itself (~/.config/atuin/config.toml) is deployed by chezmoi.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

data="$HOME/.local/share/atuin"

if ! command -v atuin >/dev/null 2>&1; then
  note "SKIPPED: atuin not installed (brew install atuin)"
  exit 0
fi

step "atuin data dir" install -d -m 0700 "$data"

logged_in() {
  local out
  out="$(atuin status 2>&1)" || return 1
  case "$out" in *"[Sync]"*) return 0 ;; *) return 1 ;; esac
}

atuin_login() {
  local s item u p k
  s="$(bw_session)"
  if [ -z "$s" ]; then
    note "PARTIAL: atuin not logged in; vault locked (bw unlock, then just apply-tags atuin)"
    return 0
  fi
  item="$(BW_SESSION="$s" bw get item atuin.sh 2>/dev/null)"
  u="$(printf '%s' "$item" | jq -r '.login.username // empty' 2>/dev/null)"
  p="$(printf '%s' "$item" | jq -r '.login.password // empty' 2>/dev/null)"
  k="$(printf '%s' "$item" | jq -r '.fields[]? | select(.name=="key") | .value' 2>/dev/null | head -n1)"
  if [ -z "$u" ] || [ -z "$p" ] || [ -z "$k" ]; then
    note "PARTIAL: Bitwarden item atuin.sh missing or incomplete; atuin login skipped"
    return 0
  fi
  # atuin expects a binary key file; `login -k` regenerates it from the mnemonic, so reset first.
  [ -e "$data/key" ] || rm -rf "$data"
  atuin login -u "$u" -p "$p" -k "$k" || return 1
  soft "atuin sync" atuin sync
}

if ! logged_in; then
  step "atuin login" atuin_login
fi

if [ ! -e "$data/.history_imported" ]; then
  soft "atuin import" sh -c 'atuin import auto 2>&1 && mkdir -p ~/.local/share/atuin && touch ~/.local/share/atuin/.history_imported'
fi
finish
