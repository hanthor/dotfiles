#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ]; then
  note "SKIPPED: kirocrew excluded on retired VPS"
  finish
fi
if [ "$(host_var kirocrew_enabled false)" != true ]; then
  note "SKIPPED: kirocrew not enabled for this host"
  finish
fi
as_root() { if [ "$EUID" = 0 ]; then "$@"; else sudo -n "$@"; fi; }
if [ ! -e "$HOME/.local/bin/kirocrew" ] || [ ! -e /etc/systemd/system/kirocrew.service ]; then
  note "SKIPPED: kirocrew binary or system service missing; install from https://github.com/kirodotdev/KiroCrew and run sudo ~/.local/bin/kirocrew service install"
  finish
fi
check_listeners() {
  local cgroup
  if [ "${1:-}" = active ]; then
    cgroup=$(as_root systemctl show kirocrew.service --property=ControlGroup --value) || return 1
    as_root ss -Htlnp | as_root python3 "$DOTFILES_DIR/units/kirocrew-sockets.py" --cgroup "$cgroup"
  else
    as_root ss -Htlnp | as_root python3 "$DOTFILES_DIR/units/kirocrew-sockets.py"
  fi
}
safe_env_file() {
  ! as_root test -L /etc/kirocrew/kirocrew.env && as_root test -f /etc/kirocrew/kirocrew.env
}
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if [ "$EUID" != 0 ] && ! sudo -n true; then step "noninteractive root access" false; finish; fi
  if ! safe_env_file; then
    step "inspect kirocrew environment (must be a regular file, not a symlink)" false
  elif mode=$(as_root stat -c '%a:%u:%g' /etc/kirocrew/kirocrew.env 2>/dev/null); then
    [ "$mode" = '600:0:0' ] && note "ok    kirocrew environment permissions" || note "would secure kirocrew environment ownership and permissions"
  else step "inspect kirocrew environment permissions" false; fi
  state=$(as_root systemctl show kirocrew.service --property=LoadState --property=ActiveState --property=UnitFileState 2>/dev/null); rc=$?
  if { [ "$rc" != 0 ] && [[ "$state" != *'LoadState=not-found'* ]]; } || [[ "$state" != *'LoadState='* || "$state" != *'ActiveState='* ]]; then
    step "inspect kirocrew service" false
  elif [[ "$state" == *'LoadState=not-found'* ]]; then
    note "would enable and start kirocrew after systemd recognizes its service"
  elif [[ "$state" != *'LoadState=loaded'* || "$state" != *'UnitFileState='* ]]; then
    step "inspect kirocrew service" false
  else
    [[ "$state" == *'ActiveState=active'* ]] || note "would start kirocrew; its future listeners cannot be inspected without starting it"
    [[ "$state" == *'UnitFileState=enabled'* ]] || note "would enable kirocrew"
  fi
  if [[ "$state" == *'ActiveState=active'* ]]; then
    step "inspect current kirocrew listeners" check_listeners active
  elif check_listeners; then
    note "current kirocrew-named listeners are localhost-only; inactive service binding is unverified"
  else step "inspect current kirocrew listeners" false; fi
  finish
fi
secure_env() {
  safe_env_file && as_root chown root:root /etc/kirocrew/kirocrew.env && as_root chmod 0600 /etc/kirocrew/kirocrew.env
}
if secure_env; then
  note "ok    secure kirocrew environment"
  step "enable and start kirocrew" as_root systemctl enable --now kirocrew.service
else
  step "secure kirocrew environment" false
fi
step "check kirocrew listens only on localhost" check_listeners active
finish
