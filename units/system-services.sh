#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
if [ "${UNITS_CHECK:-0}" = 1 ] && [ "$MACHINE" != matrix ] && [ "$MACHINE" != telengana ] && [ "$IS_TERMUX" != 1 ]; then
  hostvars="$DOTFILES_DIR/host_vars/$MACHINE.yml"
  if [ -e "$hostvars" ] || [ -L "$hostvars" ]; then
    if [ ! -f "$hostvars" ] || [ ! -r "$hostvars" ] || ! cat "$hostvars" >/dev/null 2>&1; then
      step "inspect host variables" false; finish
    fi
  elif [ ! -d "$DOTFILES_DIR/host_vars" ] || [ ! -x "$DOTFILES_DIR/host_vars" ]; then
    step "inspect host variables directory" false; finish
  fi
fi

# Nothing on the retired VPSes may be restarted or otherwise altered.
if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ] || [ "$IS_TERMUX" = 1 ] || [ "$(host_var skip_systemd false)" = true ]; then
  note "SKIPPED: system services excluded on this host"
  finish
fi

root() {
  if [ "$(id -u)" = 0 ]; then "$@"; else sudo -n "$@"; fi
}
check_file() {
  local src="$1" dest="$2" mode="$3" rc actual parent
  CHECK_CHANGED=0
  if [ ! -f "$src" ] || [ ! -r "$src" ]; then
    echo "Cannot inspect source: $src" >&2; return 1
  fi
  if [ ! -e "$dest" ]; then
    parent=$(dirname "$dest")
    while [ ! -e "$parent" ] && [ "$parent" != / ]; do parent=$(dirname "$parent"); done
    if [ ! -d "$parent" ] || [ ! -x "$parent" ]; then
      echo "Cannot inspect destination: $dest" >&2; return 1
    fi
    if ! cat "$src" >/dev/null; then echo "Cannot read source: $src" >&2; return 1; fi
    CHECK_CHANGED=1
    note "would install $dest"
    return 0
  fi
  if [ ! -f "$dest" ] || [ ! -r "$dest" ]; then
    echo "Cannot inspect destination: $dest" >&2; return 1
  fi
  if cmp -s "$src" "$dest"; then :; else
    rc=$?
    if [ "$rc" != 1 ]; then echo "Cannot compare $dest" >&2; return 1; fi
    CHECK_CHANGED=1
    note "would update $dest"
  fi
  actual=$(stat -Lc '%a' "$dest") || return 1
  [ "$actual" = "$mode" ] || note "would set mode $mode on $dest"
}
check_enabled() {
  local scope="$1" unit="$2" state rc
  local -a args=()
  [ "$scope" != user ] || args+=(--user)
  CHECK_ACTIVE=0
  if state=$(systemctl "${args[@]}" is-enabled "$unit" 2>/dev/null); then rc=0; else rc=$?; fi
  case "$state:$rc" in
    enabled:0) ;;
    disabled:1|masked:1|masked-runtime:1|not-found:1|not-found:4|static:0|indirect:0|indirect:1|linked:0|linked-runtime:0|enabled-runtime:0|generated:0|transient:0|alias:0)
      note "would enable $unit" ;;
    *) echo "Cannot inspect enabled state of $unit" >&2; return 1 ;;
  esac
  if state=$(systemctl "${args[@]}" is-active "$unit" 2>/dev/null); then rc=0; else rc=$?; fi
  case "$state:$rc" in
    active:0|reloading:0|refreshing:0) CHECK_ACTIVE=1 ;;
    inactive:3|failed:3|activating:3|deactivating:3|unknown:3|unknown:4)
      note "would start $unit" ;;
    *) echo "Cannot inspect active state of $unit" >&2; return 1 ;;
  esac
}
check_podman() {
  local login groups rc actual changed
  local dest=/etc/systemd/system/podman.socket.d/group-access.conf
  local dir=/etc/systemd/system/podman.socket.d
  if [ ! -e /usr/bin/podman ]; then
    note "SKIPPED: system podman not installed"
    return 0
  fi
  login=$(id -un) || return 1
  if getent group podman >/dev/null; then :; else
    rc=$?
    [ "$rc" = 2 ] || return "$rc"
    note "would create podman group"
  fi
  groups=$(id -nG "$login") || return 1
  case " $groups " in *' podman '*) ;; *) note "would add $login to podman group" ;; esac
  printf '[Socket]\nSocketGroup=podman\nSocketMode=0660\nDirectoryMode=0710\n' > "$tmp/podman-group.conf" || return 1
  if [ -e "$dir" ]; then
    [ -d "$dir" ] || { echo "Cannot inspect directory: $dir" >&2; return 1; }
    actual=$(stat -Lc '%a' "$dir") || return 1
    [ "$actual" = 755 ] || note "would set mode 755 on $dir"
  else
    note "would create $dir"
  fi
  check_file "$tmp/podman-group.conf" "$dest" 644 || return 1
  changed=$CHECK_CHANGED
  check_enabled system podman.socket || return 1
  if [ "$changed" = 1 ]; then
    note "would reload system systemd"
    [ "$CHECK_ACTIVE" != 1 ] || note "would restart podman.socket"
  fi
}
configure_podman() {
  if [ "${UNITS_CHECK:-0}" = 1 ]; then check_podman; return; fi
  local login groups group_status was_active=0 changed=0
  local dest=/etc/systemd/system/podman.socket.d/group-access.conf
  local content="$tmp/podman-group.conf"
  if [ ! -e /usr/bin/podman ]; then
    note "SKIPPED: system podman not installed"
    return 0
  fi
  login=$(id -un) || return 1
  if getent group podman >/dev/null; then
    :
  else
    group_status=$?
    [ "$group_status" = 2 ] || return "$group_status"
    root groupadd --system podman || return 1
  fi
  groups=$(id -nG "$login") || return 1
  case " $groups " in
    *' podman '*) ;;
    *) root usermod -a -G podman "$login" || return 1 ;;
  esac
  printf '[Socket]\nSocketGroup=podman\nSocketMode=0660\nDirectoryMode=0710\n' > "$content" || return 1
  root install -d -m 0755 /etc/systemd/system/podman.socket.d || return 1
  if [ ! -f "$dest" ] || ! cmp -s "$content" "$dest"; then
    changed=1
    root install -m 0644 "$content" "$dest" || return 1
  else
    root chmod 0644 "$dest" || return 1
  fi
  if root systemctl is-active --quiet podman.socket; then was_active=1; fi
  root systemctl daemon-reload || return 1
  root systemctl enable --now podman.socket || return 1
  # A running socket must be reopened for changed ownership/mode to take effect.
  # A socket just started already used the new settings and needs no restart.
  if [ "$changed" = 1 ] && [ "$was_active" = 1 ]; then
    root systemctl restart podman.socket || return 1
  fi
}

tmp=$(mktemp -d) || { step "create temporary directory" false; finish; }
trap 'rm -rf "$tmp"' EXIT
step "configure system podman socket" configure_podman

# Laptop user units are owned by laptop-services.sh; the system socket above
# applies to laptops too, so both units can run without touching the same file.
if [ "$(host_var is_laptop false)" = true ]; then
  finish
fi

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -S "$XDG_RUNTIME_DIR/bus" ]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
fi
brew_prefix=$(host_var brew_prefix /home/linuxbrew/.linuxbrew)
delay=$(host_var dotfiles_update_delay_seconds 60)
if [[ ! "$delay" =~ ^[0-9]+$ ]]; then
  step "invalid dotfiles update delay" false
  finish
fi
unitdir="$HOME/.config/systemd/user"
changed=0
install_unit() {
  local src="$1" dest="$unitdir/$2"
  if [ "${UNITS_CHECK:-0}" = 1 ]; then
    check_file "$src" "$dest" 644 || return 1
    [ "$CHECK_CHANGED" != 1 ] || changed=1
    return 0
  fi
  if [ ! -f "$dest" ] || ! cmp -s "$src" "$dest"; then changed=1; fi
  install_if_changed "$src" "$dest" 0644
}

# Render the non-laptop branches of the migrated service templates without
# requiring Jinja on the host.
render_service() {
  local template="$1" dest="$2" line branch=1
  : > "$dest" || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      '{% if is_laptop | bool %}') branch=0; continue ;;
      '{% else %}') branch=1; continue ;;
      '{% endif %}') branch=1; continue ;;
    esac
    [ "$branch" = 1 ] || continue
    line=${line//'{{ brew_prefix }}'/"$brew_prefix"}
    line=${line//"{{ ansible_facts['env']['HOME'] }}"/"$HOME"}
    line=${line//'{{ dotfiles_update_delay_seconds | default(60) }}'/"$delay"}
    if [[ "$line" == *'{{'* || "$line" == *'{%'* ]]; then
      echo "Unsupported system service template expression" >&2
      return 1
    fi
    printf '%s\n' "$line" >> "$dest" || return 1
  done < "$template"
}
templates="$DOTFILES_DIR/units/system-services"
update_ready=0
timer_ready=0
atuin_ready=0
if render_service "$templates/dotfiles-update.service.j2" "$tmp/dotfiles-update.service" && install_unit "$tmp/dotfiles-update.service" dotfiles-update.service; then
  update_ready=1
  note "ok    deploy dotfiles update service"
else
  step "render and deploy dotfiles update service" false
fi
if install_unit "$templates/dotfiles-update.timer.j2" dotfiles-update.timer; then
  timer_ready=1
  note "ok    deploy dotfiles update timer"
else
  step "deploy dotfiles update timer" false
fi
if render_service "$templates/atuin-daemon.service.j2" "$tmp/atuin-daemon.service" && install_unit "$tmp/atuin-daemon.service" atuin-daemon.service; then
  atuin_ready=1
  note "ok    deploy atuin daemon"
else
  step "render and deploy atuin daemon" false
fi
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  [ "$changed" != 1 ] || note "would reload user systemd"
  if [ "$update_ready" = 1 ] && [ "$timer_ready" = 1 ]; then
    step "inspect dotfiles update timer" check_enabled user dotfiles-update.timer
  fi
  if [ "$atuin_ready" = 1 ]; then
    step "inspect atuin daemon" check_enabled user atuin-daemon.service
  fi
  finish
fi
if [ "$changed" = 1 ]; then
  if ! systemctl --user daemon-reload; then
    step "reload user systemd" false
    finish
  fi
fi
if [ "$update_ready" = 1 ] && [ "$timer_ready" = 1 ]; then
  step "enable and start dotfiles update timer" systemctl --user enable --now dotfiles-update.timer
fi
if [ "$atuin_ready" = 1 ]; then
  step "enable and start atuin daemon" systemctl --user enable --now atuin-daemon.service
fi
finish
