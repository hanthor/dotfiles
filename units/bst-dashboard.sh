#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ]; then
  note "SKIPPED: dashboard excluded on retired VPS"
  finish
fi
if [ "$MACHINE" = karnataka ]; then
  dashboard_dir=/var/home/james/dev/kde-linux
  image=aurora
else
  dashboard_dir=/var/home/james/dev/dakota
  image=dakota
fi
if [ ! -e "$dashboard_dir" ]; then
  note "SKIPPED: dashboard project does not exist: $dashboard_dir"
  finish
fi
as_root() { if [ "$EUID" = 0 ]; then "$@"; else sudo -n "$@"; fi; }
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -S "$XDG_RUNTIME_DIR/bus" ]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
fi
tmp=$(mktemp) || { step "create dashboard temporary file" false; finish; }
trap 'rm -f "$tmp"' EXIT
unit="$HOME/.config/systemd/user/bst-dashboard.service"
changed=0
content_changed=0
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if python3 "$DOTFILES_DIR/units/service-templates.py" dashboard "$DOTFILES_DIR/units/bst-dashboard/bst-dashboard.service.j2" "$dashboard_dir" "$image" > "$tmp"; then
    if [ ! -e "$unit" ] && [ ! -L "$unit" ]; then
      note "would deploy dashboard user service, reload user systemd, and start or restart dashboard"
    elif mode=$(stat -c %a "$unit"); then
      cmp -s "$tmp" "$unit"; rc=$?
      case "$rc" in
        0) [ "$mode" = 644 ] && note "ok    dashboard user service" || note "would set dashboard service permissions and reload user systemd" ;;
        1) note "would deploy dashboard user service, reload user systemd, and start or restart dashboard" ;;
        *) step "compare dashboard user service" false ;;
      esac
    else step "inspect dashboard user service" false; fi
  else step "render dashboard user service" false; fi
  state=$(systemctl --user show bst-dashboard.service --property=LoadState --property=ActiveState --property=UnitFileState 2>/dev/null); rc=$?
  if { [ "$rc" != 0 ] && [[ "$state" != *'LoadState=not-found'* ]]; } || [[ "$state" != *'LoadState='* || "$state" != *'ActiveState='* ]]; then
    step "inspect dashboard user service" false
  elif [[ "$state" == *'LoadState=not-found'* ]]; then
    note "would enable and start dashboard after deployment"
  elif [[ "$state" != *'LoadState=loaded'* || "$state" != *'UnitFileState='* ]]; then
    step "inspect dashboard user service" false
  else
    [[ "$state" == *'ActiveState=active'* ]] || note "would start dashboard"
    [[ "$state" == *'UnitFileState=enabled'* ]] || note "would enable dashboard"
  fi
  if linger=$(loginctl show-user "${USER:-$(id -un)}" --property=Linger --value 2>/dev/null); then
    case "$linger" in yes) note "ok    user linger" ;; no) note "would enable user linger" ;; *) step "inspect user linger" false ;; esac
  else step "inspect user linger" false; fi
  finish
fi
if python3 "$DOTFILES_DIR/units/service-templates.py" dashboard "$DOTFILES_DIR/units/bst-dashboard/bst-dashboard.service.j2" "$dashboard_dir" "$image" > "$tmp"; then
  if [ ! -f "$unit" ] || ! cmp -s "$tmp" "$unit"; then content_changed=1; changed=1; fi
  if [ "$(stat -c %a "$unit" 2>/dev/null)" != 644 ]; then changed=1; fi
  if install_if_changed "$tmp" "$unit" 0644; then
    note "ok    deploy dashboard user service"
    if [ "$changed" = 0 ] || systemctl --user daemon-reload; then
      if [ "$content_changed" = 1 ]; then
        if systemctl --user enable bst-dashboard.service; then
          note "ok    enable dashboard"
          step "start or restart dashboard" systemctl --user restart bst-dashboard.service
        else
          step "enable dashboard" false
        fi
      else
        step "enable and start dashboard" systemctl --user enable --now bst-dashboard.service
      fi
    else
      step "reload dashboard user systemd" false
    fi
  else
    step "deploy dashboard user service" false
  fi
else
  step "render dashboard user service" false
fi
step "enable user linger" as_root loginctl enable-linger "${USER:-$(id -un)}"
finish
