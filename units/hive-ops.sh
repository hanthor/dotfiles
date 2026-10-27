#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ "${UNITS_CHECK:-0}" = 1 ] && { [ -e "$DOTFILES_DIR/host_vars/$MACHINE.yml" ] || [ -L "$DOTFILES_DIR/host_vars/$MACHINE.yml" ]; } && { [ ! -f "$DOTFILES_DIR/host_vars/$MACHINE.yml" ] || [ ! -r "$DOTFILES_DIR/host_vars/$MACHINE.yml" ]; }; then
  step "inspect host variables" false
  finish
fi
unitdir="$HOME/.config/systemd/user"
bindir="$HOME/.local/bin"
enabled=$(host_var hive_ops_enabled false)
# Never stop or alter anything on the retired VPSes, even if stale files exist.
if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ] || [ "$IS_TERMUX" = 1 ]; then
  note "SKIPPED: hive operations excluded on this host"
  finish
fi
if [ "$enabled" != true ] && [ ! -f "$unitdir/hive-watchdog.timer" ]; then
  note "SKIPPED: hive operations disabled"
  finish
fi
if ! command -v yq >/dev/null 2>&1; then
  step "check hive host and timer configuration (yq required)" false
  finish
fi
vps=$(MACHINE="$MACHINE" yq '.all.children.vps.hosts | has(strenv(MACHINE))' "$DOTFILES_DIR/inventory.yml") || { step "check VPS membership" false; finish; }
case "$vps" in
  true) note "SKIPPED: hive operations excluded on VPS"; finish ;;
  false) ;;
  *) step "check VPS membership" false; finish ;;
esac
hostfile="$DOTFILES_DIR/host_vars/$MACHINE.yml"
sourcefile="$DOTFILES_DIR/units/hive-ops/defaults.yml"
if [ -f "$hostfile" ]; then
  has_timers=$(yq 'has("hive_ops_timers")' "$hostfile") || { step "read hive timer overrides" false; finish; }
  if [ "${UNITS_CHECK:-0}" = 1 ] && [ "$has_timers" != true ] && [ "$has_timers" != false ]; then
    step "inspect hive timer overrides" false
    finish
  fi
  [ "$has_timers" = true ] && sourcefile="$hostfile"
fi
timer_text=$(yq -r '.hive_ops_timers[]' "$sourcefile") || { step "read hive timers" false; finish; }
if [ -z "$timer_text" ]; then
  step "hive timer list is empty" false
  finish
fi
mapfile -t timers <<< "$timer_text"
for timer in "${timers[@]}"; do
  if [[ ! "$timer" =~ ^(hive|pi)-[a-z0-9-]+$ ]]; then
    step "invalid hive timer name" false
    finish
  fi
done
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -S "$XDG_RUNTIME_DIR/bus" ]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
fi
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if [ "$enabled" != true ]; then
    for timer in "${timers[@]}"; do
      [ ! -f "$unitdir/$timer.timer" ] || note "CHANGE: disable and stop $timer.timer"
      for file in "$unitdir/$timer.timer" "$unitdir/$timer.service" "$unitdir/$timer.service.d/kubeconfig.conf"; do
        [ ! -e "$file" ] && [ ! -L "$file" ] || note "CHANGE: remove $file"
      done
    done
    for helper in hive-peak.sh hive-rotate.sh hive-tiers.sh; do
      [ ! -e "$bindir/$helper" ] && [ ! -L "$bindir/$helper" ] || note "CHANGE: remove $bindir/$helper"
    done
    finish
  fi

  # Compare without exposing file contents; drop-ins contain host-specific paths.
  check_file() { # source, destination, expected mode
    local src="$1" dest="$2" expected="$3" rc mode
    if [ ! -f "$src" ] || [ ! -r "$src" ]; then
      step "read $src" false
    elif [ ! -e "$dest" ] && [ ! -L "$dest" ]; then
      note "CHANGE: install $dest"
    elif [ ! -f "$dest" ] || [ ! -r "$dest" ]; then
      step "inspect $dest" false
    else
      cmp -s "$src" "$dest"; rc=$?
      case "$rc" in
        0) ;;
        1) note "CHANGE: update $dest" ;;
        *) step "compare $dest" false ;;
      esac
      mode=$(stat -c %a "$dest") || { step "inspect mode of $dest" false; return; }
      [ "$mode" = "$expected" ] || note "CHANGE: set mode of $dest to $expected"
    fi
  }
  kubeconfig=$(host_var hive_ops_kubeconfig "$HOME/.kube/config-aws-migration")
  hive_path=$(host_var hive_ops_path '/home/linuxbrew/.linuxbrew/bin:/usr/local/bin:/usr/bin:/bin')
  for helper in hive-peak.sh hive-rotate.sh hive-tiers.sh; do
    check_file "$DOTFILES_DIR/units/hive-ops/bin/$helper" "$bindir/$helper" 755
  done
  for timer in "${timers[@]}"; do
    for suffix in service timer; do
      check_file "$DOTFILES_DIR/units/hive-ops/systemd/$timer.$suffix" "$unitdir/$timer.$suffix" 644
    done
    dropin="$unitdir/$timer.service.d/kubeconfig.conf"
    if [ ! -e "$dropin" ] && [ ! -L "$dropin" ]; then
      note "CHANGE: install $dropin"
    elif [ ! -f "$dropin" ] || [ ! -r "$dropin" ]; then
      step "inspect $dropin" false
    else
      printf '[Service]\nEnvironment=KUBECONFIG=%s\nEnvironment=PATH=%s\n' "$kubeconfig" "$hive_path" | cmp -s - "$dropin"; rc=$?
      case "$rc" in
        0) ;;
        1) note "CHANGE: update $dropin" ;;
        *) step "compare $dropin" false ;;
      esac
      mode=$(stat -c %a "$dropin") || { step "inspect mode of $dropin" false; continue; }
      [ "$mode" = 644 ] || note "CHANGE: set mode of $dropin to 644"
    fi
    state=$(systemctl --user show --property=LoadState --value "$timer.timer") || { step "check $timer.timer" false; continue; }
    case "$state" in
      not-found) note "CHANGE: enable and start $timer.timer" ;;
      loaded)
        timer_enabled=$(systemctl --user show --property=UnitFileState --value "$timer.timer") || { step "check $timer.timer enablement" false; continue; }
        active=$(systemctl --user show --property=ActiveState --value "$timer.timer") || { step "check $timer.timer activity" false; continue; }
        if [ -z "$timer_enabled" ] || [ -z "$active" ]; then
          step "inspect $timer.timer state" false
        else
          [ "$timer_enabled" = enabled ] || note "CHANGE: enable $timer.timer"
          [ "$active" = active ] || note "CHANGE: start $timer.timer"
        fi
        ;;
      *) step "check $timer.timer load state" false ;;
    esac
  done
  finish
fi


if [ "$enabled" != true ]; then
  removed=0
  for timer in "${timers[@]}"; do
    if [ -f "$unitdir/$timer.timer" ]; then
      if ! systemctl --user disable --now "$timer.timer"; then
        step "disable $timer.timer" false
        continue
      fi
    fi
    if rm -f "$unitdir/$timer.timer" "$unitdir/$timer.service" "$unitdir/$timer.service.d/kubeconfig.conf"; then
      rmdir "$unitdir/$timer.service.d" 2>/dev/null || :
      removed=1
    else
      step "remove $timer units" false
    fi
  done
  if [ "$UNIT_FAILED" = 0 ]; then
    step "remove hive helpers" rm -f "$bindir/hive-peak.sh" "$bindir/hive-rotate.sh" "$bindir/hive-tiers.sh"
  fi
  [ "$removed" = 0 ] || step "reload user systemd" systemctl --user daemon-reload
  finish
fi

kubeconfig=$(host_var hive_ops_kubeconfig "$HOME/.kube/config-aws-migration")
hive_path=$(host_var hive_ops_path '/home/linuxbrew/.linuxbrew/bin:/usr/local/bin:/usr/bin:/bin')
changed=0
for helper in hive-peak.sh hive-rotate.sh hive-tiers.sh; do
  step "deploy $helper" install_if_changed "$DOTFILES_DIR/units/hive-ops/bin/$helper" "$bindir/$helper" 0755
done
for timer in "${timers[@]}"; do
  for suffix in service timer; do
    src="$DOTFILES_DIR/units/hive-ops/systemd/$timer.$suffix"
    dest="$unitdir/$timer.$suffix"
    if [ ! -f "$dest" ] || ! cmp -s "$src" "$dest"; then changed=1; fi
    step "deploy $timer.$suffix" install_if_changed "$src" "$dest" 0644
  done
  dropin="$unitdir/$timer.service.d/kubeconfig.conf"
  content=$(printf '[Service]\nEnvironment=KUBECONFIG=%s\nEnvironment=PATH=%s\n' "$kubeconfig" "$hive_path")
  if [ ! -f "$dropin" ] || [ "$(cat "$dropin")" != "$content" ]; then
    changed=1
    if mkdir -p "$(dirname "$dropin")" && printf '%s\n' "$content" > "$dropin" && chmod 0644 "$dropin"; then
      note "ok    $timer drop-in"
    else
      step "$timer drop-in" false
    fi
  else
    step "$timer drop-in mode" chmod 0644 "$dropin"
  fi
done
[ "$UNIT_FAILED" = 0 ] || finish
if [ "$changed" = 1 ]; then
  if ! systemctl --user daemon-reload; then
    step "reload user systemd" false
    finish
  fi
fi
for timer in "${timers[@]}"; do
  step "enable and start $timer.timer" systemctl --user enable --now "$timer.timer"
done
finish
