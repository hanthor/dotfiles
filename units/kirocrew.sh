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
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if [ "$EUID" != 0 ] && ! sudo -n true; then step "noninteractive root access" false; finish; fi
  if mode=$(as_root stat -c '%a:%u:%g' /etc/kirocrew/kirocrew.env 2>/dev/null); then
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
  if as_root ss -Htlnp | python3 "$DOTFILES_DIR/units/kirocrew-sockets.py"; then
    note "ok    current kirocrew listeners are localhost-only"
  else step "inspect current kirocrew listeners" false; fi
  finish
fi
secure_env() {
  as_root chown root:root /etc/kirocrew/kirocrew.env && as_root chmod 0600 /etc/kirocrew/kirocrew.env
}
if secure_env; then
  note "ok    secure kirocrew environment"
  step "enable and start kirocrew" as_root systemctl enable --now kirocrew.service
else
  step "secure kirocrew environment" false
fi
check_listeners() {
  as_root ss -Htlnp | python3 "$DOTFILES_DIR/units/kirocrew-sockets.py"
}
step "check kirocrew listens only on localhost" check_listeners
finish
