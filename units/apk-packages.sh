#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=units/platform-config.bash
. "$DOTFILES_DIR/units/platform-config.bash"
# shellcheck source=units/apk-packages.conf
. "$DOTFILES_DIR/units/apk-packages.conf"

if [ "$IS_MUSL" != 1 ]; then
  note 'SKIPPED: APK packages require musl'
  finish
fi

check_apk_packages() {
  local installed pkg line found
  installed="$(apk info 2>/dev/null)" || { echo 'Cannot inspect installed APK packages' >&2; return 1; }
  for pkg in "$@"; do
    found=0
    while IFS= read -r line; do [ "$line" != "$pkg" ] || found=1; done <<< "$installed"
    if [ "$found" = 0 ]; then note "WOULD install APK package $pkg"; else note "ok    APK package $pkg"; fi
  done
}
check_podman_service() {
  local unit="$1" enabled active rc
  enabled="$(systemctl is-enabled "$unit" 2>/dev/null)"; rc=$?
  case "$enabled:$rc" in
    enabled:0|enabled-runtime:0|disabled:1|masked:1|masked-runtime:1|static:0|indirect:0|linked:0|linked-runtime:0|generated:0|transient:0|not-found:1) ;;
    *) echo "Cannot inspect $unit enablement" >&2; return 1 ;;
  esac
  active="$(systemctl is-active "$unit" 2>/dev/null)"; rc=$?
  case "$active:$rc" in
    active:0|reloading:0|refreshing:0|inactive:3|failed:3|activating:3|deactivating:3) ;;
    unknown:4) [ "$enabled" = not-found ] || { echo "Cannot inspect $unit activity" >&2; return 1; } ;;
    *) echo "Cannot inspect $unit activity" >&2; return 1 ;;
  esac
  if [ "$enabled" != enabled ] || [ "$active" != active ]; then
    note "WOULD enable and start $unit (enabled=$enabled, active=$active)"
  else
    note "ok    $unit enabled and active"
  fi
}
check_podman_group() {
  local user groups
  user="${USER:-$(id -un)}"
  groups="$(id -nG "$user")" || return 1
  case " $groups " in
    *' podman '*) note 'ok    podman group membership' ;;
    *) note "WOULD add $user to podman group" ;;
  esac
}
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  note 'WOULD update APK package cache (not inspected offline)'
  step 'inspect APK packages' check_apk_packages "${APK_BOOTSTRAP[@]}" "${APK_OPTIONAL[@]}" "${APK_PACKAGES[@]}"
  note 'WOULD run npm install -g @bitwarden/cli (current registry version not inspected)'
  if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ]; then
    note 'SKIPPED: podman services on retired VPS'
  else
    step 'inspect podman service' check_podman_service podman
    step 'inspect podman socket' check_podman_service podman.socket
  fi
  step 'inspect podman group membership' check_podman_group
  finish
fi

update_cache() {
  local attempt
  for attempt in 1 2 3 4 5; do
    platform_root apk update && return 0
    [ "$attempt" = 5 ] || sleep 5
  done
  return 1
}
install_packages() {
  # The role's state=present does not upgrade already installed packages.
  local pkg rc=0 missing=()
  for pkg in "$@"; do
    apk info -e "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
  done
  [ "${#missing[@]}" != 0 ] || return 0
  platform_root apk add --no-upgrade "${missing[@]}" && return 0
  # An unavailable package must not prevent unrelated packages being installed.
  for pkg in "${missing[@]}"; do
    if ! platform_root apk add --no-upgrade "$pkg"; then
      echo "APK package unavailable or installation failed: $pkg" >&2
      rc=1
    fi
  done
  return "$rc"
}
add_podman_group() {
  local user groups
  user="${USER:-$(id -un)}"
  groups="$(id -nG "$user")" || return 1
  case " $groups " in *' podman '*) return 0 ;; esac
  platform_root usermod -a -G podman "$user" || return 1
  note 'User added to podman group; log out and back in to use rootless podman.'
}

soft 'APK cache update' update_cache
step 'APK bootstrap packages' install_packages "${APK_BOOTSTRAP[@]}"
soft 'APK optional mise' install_packages "${APK_OPTIONAL[@]}"
step 'APK packages' install_packages "${APK_PACKAGES[@]}"
step 'Bitwarden CLI via npm' platform_root npm install -g @bitwarden/cli
if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ]; then
  note 'SKIPPED: podman services on retired VPS'
else
  soft 'podman service' platform_root systemctl enable --now podman
  soft 'podman socket' platform_root systemctl enable --now podman.socket
fi
step 'podman group membership' add_podman_group
finish
