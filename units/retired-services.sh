#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# Only files explicitly listed in the role's canonical inventory are eligible.
retired_unit_name() {
  local name=${1##*/} stem=${1##*/}
  stem=${stem%.*}
  case "$name" in
    *.container) printf '%s.service\n' "$stem" ;;
    *.volume) printf '%s-volume.service\n' "$stem" ;;
    *.network) printf '%s-network.service\n' "$stem" ;;
    *.pod) printf '%s-pod.service\n' "$stem" ;;
    *) printf '%s\n' "$name" ;;
  esac
}

# A missing generated unit is normal, but any other systemd error is not.
retired_stop() {
  local scope=$1 path=$2 unit state
  local -a ctl=(systemctl)
  [ "$scope" = user ] && ctl+=(--user)
  unit=$(retired_unit_name "$path")
  state=$("${ctl[@]}" show --property=LoadState --value "$unit" 2>/dev/null) || {
    [ "$state" = not-found ] && return 0
    return 1
  }
  [ "$state" = not-found ] && return 0
  [ "$state" = loaded ] || return 1
  case "$path" in
    *.container|*.volume|*.network|*.pod) "${ctl[@]}" stop "$unit" ;;
    *) "${ctl[@]}" disable --now "$unit" ;;
  esac
}

retired_cleanup_user() {
  local file user_changed=0
  for file in "$@"; do
    [ -n "$file" ] || continue
    file="$HOME/.config/containers/systemd/$file"
    [ -e "$file" ] || [ -L "$file" ] || continue
    if ! retired_stop user "$file"; then step "stop retired user unit $file" false; continue; fi
    if rm -f -- "$file"; then user_changed=1; else step "remove retired user unit $file" false; fi
  done
  if [ "$user_changed" = 1 ]; then step "reload user systemd" systemctl --user daemon-reload; fi
}

retired_main() {
  local vps file found=0 system_changed=0 user_changed=0
  local -a system_units user_units rootcmd=()
  case "$MACHINE" in matrix|telengana) note "SKIPPED: retired VPS"; finish ;; esac
  if [ "$IS_TERMUX" = 1 ] || [ "$(uname -s)" != Linux ] || [ ! -d /run/systemd/system ]; then
    note "SKIPPED: retired services require native systemd"; finish
  fi
  if ! command -v yq >/dev/null 2>&1 || ! command -v systemctl >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
    step "retired service dependencies (yq, python3 and systemctl)" false; finish
  fi
  vps=$(python3 "$DOTFILES_DIR/units/osquery_native_inventory.py" groups "$DOTFILES_DIR/inventory.yml" "$MACHINE" vps) || { step "check VPS membership" false; finish; }
  case "$vps" in true) note "SKIPPED: VPS"; finish ;; false) ;; *) step "check VPS membership" false; finish ;; esac
  local defaults="$DOTFILES_DIR/units/retired-services/defaults/main.yml" system_list user_list
  system_list=$(yq -r '.retired_services_system_units[]' "$defaults") || { step "read retired system units" false; finish; }
  user_list=$(yq -r '.retired_services_user_units[]' "$defaults") || { step "read retired user units" false; finish; }
  mapfile -t system_units <<< "$system_list"
  mapfile -t user_units <<< "$user_list"
  export XDG_RUNTIME_DIR="/run/user/$(id -u)"
  if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -S "$XDG_RUNTIME_DIR/bus" ]; then
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
  fi
  for file in "${system_units[@]}"; do
    [ -n "$file" ] || continue
    if [ -e "$file" ] || [ -L "$file" ]; then found=1; break; fi
  done
  if [ "${UNITS_CHECK:-0}" = 1 ]; then
    # lstat distinguishes absent paths from inaccessible parent directories.
    retired_verify_paths() {
      python3 -c 'import os, sys
failed = False
for path in sys.argv[1:]:
    if not path:
        continue
    try:
        os.lstat(path)
    except FileNotFoundError:
        pass
    except OSError as error:
        print("cannot inspect retired path %s: %s" % (path, error), file=sys.stderr)
        failed = True
sys.exit(1 if failed else 0)' "$@"
    }
    local -a user_paths=()
    for file in "${user_units[@]}"; do
      [ -z "$file" ] || user_paths+=("$HOME/.config/containers/systemd/$file")
    done
    retired_verify_paths "${system_units[@]}" || step "inspect retired system paths" false
    retired_verify_paths "${user_paths[@]}" || step "inspect retired user paths" false
    retired_inspect() {
      local scope=$1 path=$2 unit state rc
      local -a ctl=(systemctl)
      [ "$scope" = user ] && ctl+=(--user)
      unit=$(retired_unit_name "$path")
      if [ "$scope" = system ]; then
        state=$("${rootcmd[@]}" "${ctl[@]}" show --property=LoadState --value "$unit" 2>/dev/null); rc=$?
      else
        state=$("${ctl[@]}" show --property=LoadState --value "$unit" 2>/dev/null); rc=$?
      fi
      if [ "$state" = not-found ]; then
        note "would remove retired $scope unit file $path (generated unit absent)"
      elif [ "$rc" = 0 ] && [ "$state" = loaded ]; then
        case "$path" in
          *.container|*.volume|*.network|*.pod) note "would stop $unit and remove retired $scope unit file $path" ;;
          *) note "would disable and stop $unit and remove retired $scope unit file $path" ;;
        esac
      else
        step "inspect retired $scope unit $unit" false
        return 1
      fi
    }
    if [ "$found" = 1 ] && [ "$(id -u)" != 0 ]; then
      if command -v sudo >/dev/null 2>&1 && sudo -n true; then rootcmd=(sudo -n); else
        step "root access for retired system units" false
        system_units=()
      fi
    fi
    for file in "${system_units[@]}"; do
      [ -e "$file" ] || [ -L "$file" ] || continue
      if retired_inspect system "$file"; then system_changed=1; fi
    done
    for file in "${user_units[@]}"; do
      [ -n "$file" ] || continue
      file="$HOME/.config/containers/systemd/$file"
      [ -e "$file" ] || [ -L "$file" ] || continue
      if retired_inspect user "$file"; then user_changed=1; fi
    done
    [ "$system_changed" = 0 ] || note "would reload system systemd after removal"
    [ "$user_changed" = 0 ] || note "would reload user systemd after removal"
    [ "$system_changed" != 0 ] || [ "$user_changed" != 0 ] || [ "$UNIT_FAILED" != 0 ] || note "ok    no retired unit files found"
    finish
  fi
  if [ "$found" = 1 ]; then
    if [ "$(id -u)" != 0 ]; then
      if command -v sudo >/dev/null 2>&1 && sudo -n true; then rootcmd=(sudo -n); else
        step "root access for retired system units" false
        system_units=()
      fi
    fi
    for file in "${system_units[@]}"; do
      [ -e "$file" ] || [ -L "$file" ] || continue
      # Pass the function itself through sudo, without trusting arbitrary unit names.
      if [ "${#rootcmd[@]}" = 0 ]; then
        retired_stop system "$file"
      else
        "${rootcmd[@]}" bash -c "$(declare -f retired_unit_name retired_stop); retired_stop system \"\$1\"" _ "$file"
      fi
      if [ "$?" -ne 0 ]; then step "stop retired system unit $file" false; continue; fi
      if "${rootcmd[@]}" rm -f -- "$file"; then system_changed=1; else step "remove retired system unit $file" false; fi
    done
    if [ "$system_changed" = 1 ]; then step "reload system systemd" "${rootcmd[@]}" systemctl daemon-reload; fi
  fi
  retired_cleanup_user "${user_units[@]}"
  finish
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then retired_main "$@"; fi
