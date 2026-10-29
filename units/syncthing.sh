#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=units/platform-config.bash
. "$DOTFILES_DIR/units/platform-config.bash"
if { [ -e "$DOTFILES_DIR/host_vars/$MACHINE.yml" ] || [ -L "$DOTFILES_DIR/host_vars/$MACHINE.yml" ]; } && { [ ! -f "$DOTFILES_DIR/host_vars/$MACHINE.yml" ] || [ ! -r "$DOTFILES_DIR/host_vars/$MACHINE.yml" ]; }; then
  step "inspect host variables" false
  finish
fi

if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ] || [ "$IS_TERMUX" = 1 ] || skipped_by_profile skip_syncthing; then
  note "SKIPPED: syncthing excluded on this host"
  finish
fi
if platform_group_contains vps; then
  note "SKIPPED: syncthing excluded on VPS"
  finish
else
  rc=$?
  if [ "$rc" -ne 1 ]; then
    step "check VPS membership" false
    finish
  fi
fi

# Remote sessions may not inherit the user's systemd bus environment.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -S "$XDG_RUNTIME_DIR/bus" ]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
fi
binary="${DOTFILES_SYSTEM_ROOT:-}/home/linuxbrew/.linuxbrew/bin/syncthing"
unit="$HOME/.config/systemd/user/syncthing.service"
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if [ ! -e "$binary" ]; then
    if [ -f "$unit" ]; then
      note "CHANGE: disable and stop syncthing.service (binary missing)"
    else
      state=$(systemctl --user show --property=LoadState --value syncthing.service) || { step "check syncthing service" false; finish; }
      case "$state" in
        not-found) note "SKIPPED: syncthing binary and service not installed" ;;
        loaded) note "CHANGE: disable and stop syncthing.service (binary missing)" ;;
        *) step "check syncthing service load state" false ;;
      esac
    fi
    finish
  fi
  src="$DOTFILES_DIR/units/syncthing/syncthing.service"
  if [ ! -f "$src" ] || [ ! -r "$src" ]; then
    step "read syncthing service source" false
  elif [ ! -e "$unit" ] && [ ! -L "$unit" ]; then
    note "CHANGE: install syncthing.service"
  elif [ -L "$unit" ]; then
    note "CHANGE: replace syncthing.service symlink"
  elif [ ! -f "$unit" ] || [ ! -r "$unit" ]; then
    step "inspect syncthing service file" false
  else
    cmp -s "$src" "$unit"; rc=$?
    case "$rc" in
      0) ;;
      1) note "CHANGE: update syncthing.service" ;;
      *) step "compare syncthing service file" false ;;
    esac
    mode=$(stat -c %a "$unit") || { step "inspect syncthing service mode" false; finish; }
    [ "$mode" = 644 ] || note "CHANGE: set syncthing.service mode 0644"
  fi
  state=$(systemctl --user show --property=LoadState --value syncthing.service) || { step "check syncthing service" false; finish; }
  case "$state" in
    not-found) note "CHANGE: enable and start syncthing.service" ;;
    loaded)
      enabled=$(systemctl --user show --property=UnitFileState --value syncthing.service) || { step "check syncthing enablement" false; finish; }
      active=$(systemctl --user show --property=ActiveState --value syncthing.service) || { step "check syncthing activity" false; finish; }
      if [ -z "$enabled" ] || [ -z "$active" ]; then
        step "inspect syncthing service state" false
      else
        [ "$enabled" = enabled ] || note "CHANGE: enable syncthing.service"
        [ "$active" = active ] || note "CHANGE: start syncthing.service"
      fi
      ;;
    *) step "check syncthing service load state" false ;;
  esac
  finish
fi
if [ ! -e "$binary" ]; then
  # A user service can also come from a system-wide user-unit directory.
  if [ -f "$unit" ]; then
    step "stop syncthing without binary" systemctl --user disable --now syncthing.service
  else
    state=$(systemctl --user show --property=LoadState --value syncthing.service) || { step "check syncthing service" false; finish; }
    case "$state" in
      not-found) note "SKIPPED: syncthing binary and service not installed" ;;
      loaded) step "stop syncthing without binary" systemctl --user disable --now syncthing.service ;;
      *) step "check syncthing service load state" false ;;
    esac
  fi
  finish
fi
install_syncthing_service() {
  local src="$DOTFILES_DIR/units/syncthing/syncthing.service" dir staged rc
  [ -f "$src" ] && [ -r "$src" ] || return 1
  if [ ! -L "$unit" ] && [ -e "$unit" ]; then
    [ -f "$unit" ] || return 1
    if cmp -s "$src" "$unit"; then
      chmod 0644 "$unit"
      return
    else
      rc=$?
      [ "$rc" = 1 ] || return "$rc"
    fi
  fi
  dir="$(dirname "$unit")"
  mkdir -p "$dir" || return 1
  staged="$(mktemp "$dir/.syncthing.service.XXXXXXXX")" || return 1
  if ! install -m 0644 "$src" "$staged" || ! mv -fT "$staged" "$unit"; then
    rm -f "$staged"
    return 1
  fi
}
if ! install_syncthing_service; then
  step "syncthing service file" false
  finish
fi
note "ok    syncthing service file"
# Reload even when the file is unchanged: a previous reload may have failed
# after installation, leaving the user manager with a stale unit definition.
if ! systemctl --user daemon-reload; then
  step "reload user systemd" false
  finish
fi
step "enable and start syncthing" systemctl --user enable --now syncthing.service
finish
