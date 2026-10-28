#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
if [ "$MACHINE" != matrix ] && [ "$MACHINE" != telengana ] && [ "$IS_TERMUX" != 1 ]; then
  hostvars="$DOTFILES_DIR/host_vars/$MACHINE.yml"
  if [ -e "$hostvars" ] || [ -L "$hostvars" ]; then
    if [ ! -f "$hostvars" ] || [ ! -r "$hostvars" ] || ! cat "$hostvars" >/dev/null 2>&1; then
      step "inspect host variables" false; finish
    fi
  elif [ ! -d "$DOTFILES_DIR/host_vars" ] || [ ! -x "$DOTFILES_DIR/host_vars" ]; then
    step "inspect host variables directory" false; finish
  fi
fi

if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ] || [ "$IS_TERMUX" = 1 ] || [ "$(host_var skip_systemd false)" = true ] || [ "$(host_var is_laptop false)" != true ]; then
  note "SKIPPED: laptop services excluded on this host"
  finish
fi
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -S "$XDG_RUNTIME_DIR/bus" ]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
fi
unitdir="$HOME/.config/systemd/user"
brew_prefix=$(host_var brew_prefix /home/linuxbrew/.linuxbrew)
delay=$(host_var dotfiles_update_delay_seconds 60)
auto_update=$(host_var dotfiles_auto_update true)
phone_apply=$(host_var phone_apply_enabled true)
if [[ ! "$delay" =~ ^[0-9]+$ ]]; then
  step "invalid dotfiles update delay" false
  finish
fi
tmp=$(mktemp -d) || { step "create temporary directory" false; finish; }
trap 'rm -rf "$tmp"' EXIT
changed=0
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
  local unit="$1" start="$2" state enabled_state rc
  if state=$(systemctl --user is-enabled "$unit" 2>/dev/null); then rc=0; else rc=$?; fi
  case "$state:$rc" in
    enabled:0) ;;
    disabled:1|masked:1|masked-runtime:1|not-found:1|not-found:4|static:0|indirect:0|indirect:1|linked:0|linked-runtime:0|enabled-runtime:0|generated:0|transient:0|alias:0)
      note "would enable $unit" ;;
    *) echo "Cannot inspect enabled state of $unit" >&2; return 1 ;;
  esac
  enabled_state=$state
  [ "$start" = 1 ] || return 0
  if state=$(systemctl --user is-active "$unit" 2>/dev/null); then rc=0; else rc=$?; fi
  case "$state:$rc" in
    active:0|reloading:0|refreshing:0) ;;
    inactive:4)
      [ "$enabled_state" = not-found ] || { echo "Cannot inspect active state of $unit" >&2; return 1; }
      note "would start $unit" ;;
    inactive:3|failed:3|activating:3|deactivating:3|unknown:3|unknown:4)
      note "would start $unit" ;;
    *) echo "Cannot inspect active state of $unit" >&2; return 1 ;;
  esac
}
check_remove() {
  local dest="$unitdir/$1" parent
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    changed=1
    note "would disable and remove $dest"
  else
    parent=$(dirname "$dest")
    while [ ! -e "$parent" ] && [ "$parent" != / ]; do parent=$(dirname "$parent"); done
    if [ ! -d "$parent" ] || [ ! -x "$parent" ]; then
      echo "Cannot inspect destination: $dest" >&2; return 1
    fi
  fi
}
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
remove_unit() {
  local name="$1"
  if [ "${UNITS_CHECK:-0}" = 1 ]; then check_remove "$name"; return; fi
  if [ -e "$unitdir/$name" ] || [ -L "$unitdir/$name" ]; then
    systemctl --user disable --now "$name" || return 1
    rm -f "$unitdir/$name" || return 1
    changed=1
  fi
}
# The old non-laptop service could be enabled on default.target. Remove only
# its managed link; leaving it would also run the laptop update before login.
remove_old_update_link() {
  local link="$unitdir/default.target.wants/dotfiles-update.service" target
  [ -L "$link" ] || return 0
  target=$(readlink "$link") || return 1
  case "$target" in
    ../dotfiles-update.service|"$unitdir/dotfiles-update.service")
      if [ "${UNITS_CHECK:-0}" = 1 ]; then note "would remove $link"; else rm -f "$link" || return 1; fi
      changed=1 ;;
  esac
}
deploy() {
  local description="$1"; shift
  if "$@"; then
    note "ok    $description"
  else
    step "$description" false
    return 1
  fi
}
update_ready=0 atuin_ready=0 mitigator_script_ready=0 mitigator_ready=0 phone_service_ready=0 phone_timer_ready=0
timer_removed=0

cat > "$tmp/dotfiles-update.service" <<EOF || { step "render dotfiles update service" false; finish; }
[Unit]
Description=Dotfiles auto-update
After=network-online.target graphical-session.target
Wants=network-online.target
PartOf=graphical-session.target

[Service]
Type=oneshot
# Wait for network to settle and desktop to stabilise before pulling
ExecStartPre=/bin/sleep $delay
# Pull latest repo changes, then run native units locally.
# Timer cannot unlock Bitwarden non-interactively, so we explicitly skip secrets.
# SSH key sync happens on manual \`dots-apply\` instead.
ExecStart=/usr/bin/env just -f $HOME/.local/share/dotfiles/Justfile apply-nosecrets
# Also update podman containers while we're at it
ExecStartPost=-/usr/bin/podman auto-update --user
ExecStartPost=-/usr/bin/sudo /usr/bin/podman auto-update
Environment="PATH=$brew_prefix/bin:%h/.local/bin:/usr/local/bin:/usr/bin:/bin"
Environment="HOME=$HOME"
# Keep output for journalctl -u dotfiles-update
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=graphical-session.target
EOF
cat > "$tmp/atuin-daemon.service" <<EOF || { step "render atuin daemon" false; finish; }
[Unit]
Description=Atuin shell history sync daemon
After=network.target

[Service]
ExecStart=/usr/bin/env atuin daemon start --force
Environment="PATH=$brew_prefix/bin:%h/.local/bin:/usr/local/bin:/usr/bin:/bin"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
if deploy "remove obsolete laptop update timer" remove_unit dotfiles-update.timer &&
   deploy "remove obsolete default-target update link" remove_old_update_link; then
  timer_removed=1
fi
if [ "$auto_update" = true ]; then
  if deploy "deploy dotfiles update service" install_unit "$tmp/dotfiles-update.service" dotfiles-update.service && [ "$timer_removed" = 1 ]; then
    update_ready=1
  fi
else
  step "disable dotfiles update service" remove_unit dotfiles-update.service
fi
deploy "deploy atuin daemon" install_unit "$tmp/atuin-daemon.service" atuin-daemon.service && atuin_ready=1
if [ "$MACHINE" = himachal ]; then
  if [ "${UNITS_CHECK:-0}" = 1 ]; then
    deploy "inspect system mitigator" check_file "$DOTFILES_DIR/units/laptop-services/system-mitigator.py" "$HOME/.local/bin/system-mitigator.py" 755 && mitigator_script_ready=1
  else
    deploy "deploy system mitigator" install_if_changed "$DOTFILES_DIR/units/laptop-services/system-mitigator.py" "$HOME/.local/bin/system-mitigator.py" 0755 && mitigator_script_ready=1
  fi
  deploy "deploy system mitigator service" install_unit "$DOTFILES_DIR/units/laptop-services/system-mitigator.service" system-mitigator.service && mitigator_ready=1
  if [ "$phone_apply" = true ]; then
    cat > "$tmp/phone-apply.service" <<EOF || { step "render phone apply service" false; finish; }
[Unit]
Description=Periodic push-apply to phone-hosted machines (termux, mumbai)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$HOME/.local/share/dotfiles
ExecStartPre=/usr/bin/git pull --ff-only
# Phone hosts are frequently unreachable (asleep, app killed, off tailnet)
# — that's expected, not an error, so each apply is allowed to fail
# without failing the service (the leading "-").
# Run the same tracked revision on each target without requiring a checkout.
ExecStart=-:/bin/bash -c "set -o pipefail; /usr/bin/git archive HEAD | /usr/bin/ssh -o BatchMode=yes termux 'mkdir -p \"\$HOME/.cache\"; d=\$(mktemp -d \"\$HOME/.cache/dotfiles-phone.XXXXXXXX\") || exit 1; tar -xf - -C \"\$d\" && DOTFILES_MACHINE=termux bash \"\$d/scripts/run-units.sh\" --no-secrets; rc=\$?; rm -rf -- \"\$d\"; exit \"\$rc\"'"
ExecStart=-:/bin/bash -c "set -o pipefail; /usr/bin/git archive HEAD | /usr/bin/ssh -o BatchMode=yes mumbai 'mkdir -p \"\$HOME/.cache\"; d=\$(mktemp -d \"\$HOME/.cache/dotfiles-phone.XXXXXXXX\") || exit 1; tar -xf - -C \"\$d\" && DOTFILES_MACHINE=mumbai bash \"\$d/scripts/run-units.sh\" --no-secrets; rc=\$?; rm -rf -- \"\$d\"; exit \"\$rc\"'"
Environment="PATH=$brew_prefix/bin:%h/.local/bin:/usr/local/bin:/usr/bin:/bin"
Environment="HOME=$HOME"
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF
    deploy "deploy phone apply service" install_unit "$tmp/phone-apply.service" phone-apply.service && phone_service_ready=1
    deploy "deploy phone apply timer" install_unit "$DOTFILES_DIR/units/laptop-services/phone-apply.timer" phone-apply.timer && phone_timer_ready=1
  else
    step "disable phone apply timer" remove_unit phone-apply.timer
    if [ "${UNITS_CHECK:-0}" = 1 ]; then
      if [ -f "$unitdir/phone-apply.service" ]; then note "would remove $unitdir/phone-apply.service"; changed=1; fi
    elif [ ! -f "$unitdir/phone-apply.timer" ] && [ -f "$unitdir/phone-apply.service" ]; then
      if rm -f "$unitdir/phone-apply.service"; then changed=1; else step "remove phone apply service" false; fi
    fi
  fi
fi
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  [ "$changed" != 1 ] || note "would reload user systemd"
  if [ "$update_ready" = 1 ]; then
    step "inspect dotfiles update on login" check_enabled dotfiles-update.service 0
  fi
  if [ "$atuin_ready" = 1 ]; then
    step "inspect atuin daemon" check_enabled atuin-daemon.service 1
  fi
  if [ "$MACHINE" = himachal ]; then
    if [ "$mitigator_script_ready" = 1 ] && [ "$mitigator_ready" = 1 ]; then
      step "inspect system mitigator service" check_enabled system-mitigator.service 1
    fi
    if [ "$phone_service_ready" = 1 ] && [ "$phone_timer_ready" = 1 ]; then
      step "inspect phone apply timer" check_enabled phone-apply.timer 1
    fi
  fi
  finish
fi
if [ "$changed" = 1 ]; then
  if ! systemctl --user daemon-reload; then
    step "reload user systemd" false
    finish
  fi
fi
# Enabling a login-triggered oneshot must not start an apply during this apply.
if [ "$update_ready" = 1 ]; then
  step "enable dotfiles update on login" systemctl --user enable dotfiles-update.service
fi
if [ "$atuin_ready" = 1 ]; then
  step "enable and start atuin daemon" systemctl --user enable --now atuin-daemon.service
fi
if [ "$MACHINE" = himachal ]; then
  if [ "$mitigator_script_ready" = 1 ] && [ "$mitigator_ready" = 1 ]; then
    step "enable and start system mitigator" systemctl --user enable --now system-mitigator.service
  fi
  if [ "$phone_service_ready" = 1 ] && [ "$phone_timer_ready" = 1 ]; then
    step "enable and start phone apply timer" systemctl --user enable --now phone-apply.timer
  fi
fi
finish
