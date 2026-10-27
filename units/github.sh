#!/usr/bin/env bash
# github unit: gh login from a Bitwarden token, git over SSH, and this machine's SSH key
# registered with GitHub as an authentication and a signing key.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

GITHUB_HOST_KEY="github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
pub="$HOME/.ssh/id_ed25519.pub"

if ! command -v gh >/dev/null 2>&1; then
  note "SKIPPED: gh not installed (just packages)"
  exit 0
fi
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  check_known_hosts() {
    local dir="$HOME/.ssh" path="$HOME/.ssh/known_hosts" mode rc
    if [ ! -e "$dir" ]; then
      note "would create $dir (mode 0700)"
    elif [ ! -d "$dir" ] || ! mode="$(stat -Lc '%a' "$dir")"; then
      note "FAIL  cannot inspect $dir"
      return 1
    elif [ "$mode" != 700 ]; then
      note "would set $dir mode 0700"
    fi
    if [ ! -e "$path" ]; then
      note "would add GitHub host key to $path"
      return 0
    fi
    if [ ! -f "$path" ]; then
      note "FAIL  cannot inspect $path"
      return 1
    fi
    grep -qF "$GITHUB_HOST_KEY" "$path" 2>/dev/null; rc=$?
    case "$rc" in
      0) note "ok    GitHub host key" ;;
      1) note "would add GitHub host key to $path" ;;
      *) note "FAIL  cannot inspect $path"; return 1 ;;
    esac
  }
  step "check github known_hosts" check_known_hosts
  if [ "${UNITS_NO_SECRETS:-0}" = 1 ]; then
    note "SKIPPED: GitHub authentication and SSH key registration (--no-secrets)"
  else
    note "FAIL  cannot safely inspect GitHub authentication or registered keys: gh may prompt via the OS keyring and Bitwarden reads may persist audit events"
    UNIT_FAILED=1
  fi
  finish
fi


known_hosts() {
  install -d -m 0700 "$HOME/.ssh" || return 1
  grep -qF "$GITHUB_HOST_KEY" "$HOME/.ssh/known_hosts" 2>/dev/null && return 0
  printf '%s\n' "$GITHUB_HOST_KEY" >> "$HOME/.ssh/known_hosts"
}

gh_login() {
  gh auth status >/dev/null 2>&1 && return 0
  local s tok
  s="$(bw_session)"
  if [ -z "$s" ]; then
    note "PARTIAL: gh not logged in; vault locked (bw unlock, then just apply-tags github)"
    return 0
  fi
  tok="$(BW_SESSION="$s" bw get password github-token 2>/dev/null)"
  if [ -z "$tok" ]; then
    note "PARTIAL: no 'github-token' item in Bitwarden; add a login item with your PAT as the password"
    return 0
  fi
  printf '%s' "$tok" | gh auth login --with-token
}

# Query each key type separately: `gh ssh-key list` exits nonzero for an empty account.
register_key() {
  local type="$1" title="$MACHINE-$2" endpoint keys
  case "$type" in
    authentication) endpoint=user/keys ;;
    signing) endpoint=user/ssh_signing_keys ;;
    *) return 1 ;;
  esac
  if ! keys="$(gh api --paginate --jq '.[].key' "$endpoint" 2>/dev/null)"; then
    note "warn: failed to list GitHub SSH $type keys; registration skipped"
    return 1
  fi
  if awk -v key="$key_body" '$2 == key { found=1 } END { exit !found }' <<<"$keys"; then return 0; fi
  if ! gh ssh-key add "$pub" --title "$title" --type "$type"; then
    note "warn: failed to upload SSH $type key for $MACHINE to GitHub"
    return 1
  fi
}

register_keys() {
  local scopes key_body
  scopes="$(gh auth status -t 2>&1 | grep -o 'Token scopes:.*' || true)"
  case "$scopes" in
    *admin:public_key*admin:ssh_signing_key*|*admin:ssh_signing_key*admin:public_key*) ;;
    *)
      note "PARTIAL: GitHub token lacks admin:public_key / admin:ssh_signing_key (have: ${scopes:-unknown}); regenerate the PAT at https://github.com/settings/tokens and update the 'github-token' item"
      return 0 ;;
  esac
  [ -f "$pub" ] || { note "warn: $pub missing; no SSH key to register"; return 1; }
  key_body="$(awk '{print $2}' "$pub")"
  local rc=0
  register_key authentication auth || rc=1
  register_key signing signing || rc=1
  return "$rc"
}

step "github known_hosts" known_hosts
if [ "${UNITS_NO_SECRETS:-0}" = 1 ]; then
  note "SKIPPED: GitHub authentication and SSH key registration (--no-secrets)"
  finish
fi
step "gh login" gh_login
step "register SSH keys" register_keys
finish
