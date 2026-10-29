#!/usr/bin/env bash
# forgejo-registry unit: `podman login` to the private Forgejo container registry from Bitwarden.
# The Bitwarden login item is named after the registry host and holds the username + a registry token.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

FORGEJO_REGISTRY="${FORGEJO_REGISTRY:-forgejo.manatee-basking.ts.net}"

if skipped_by_profile skip_forgejo; then
  note "SKIPPED: skip_forgejo or vm-test"
  exit 0
fi
if ! command -v podman >/dev/null 2>&1; then
  note "SKIPPED: podman not installed"
  exit 0
fi
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  note "FAIL  cannot safely inspect $FORGEJO_REGISTRY login: Podman credential helpers may prompt; registry check unsupported"
  exit 1
fi
if podman login --get-login "$FORGEJO_REGISTRY" >/dev/null 2>&1; then
  note "ok    already logged in to $FORGEJO_REGISTRY"
  exit 0
fi
s="$(bw_session)"
if [ -z "$s" ]; then
  note "SKIPPED: vault locked or --no-secrets; not logged in to $FORGEJO_REGISTRY"
  exit 0
fi

registry_login() {
  local user pass
  user="$(BW_SESSION="$s" bw get username "$FORGEJO_REGISTRY" 2>/dev/null)" || user=""
  pass="$(BW_SESSION="$s" bw get password "$FORGEJO_REGISTRY" 2>/dev/null)" || pass=""
  user="${user#"${user%%[![:space:]]*}"}"
  user="${user%"${user##*[![:space:]]}"}"
  if [ -z "$user" ] || [ -z "$pass" ]; then
    note "PARTIAL: Forgejo credential ($FORGEJO_REGISTRY) not found in Bitwarden — add a login item with that name holding the registry token"
    return 0
  fi
  printf '%s' "$pass" | podman login "$FORGEJO_REGISTRY" -u "$user" --password-stdin
}
step "podman login $FORGEJO_REGISTRY" registry_login
finish
