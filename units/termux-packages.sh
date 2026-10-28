#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=units/platform-config.bash
. "$DOTFILES_DIR/units/platform-config.bash"
# shellcheck source=units/termux-packages.conf
. "$DOTFILES_DIR/units/termux-packages.conf"
# shellcheck source=units/package-config.bash
. "$DOTFILES_DIR/units/package-config.bash"

if platform_group_contains termux_hosts; then :; else
  rc=$?
  if [ "$rc" = 1 ]; then note 'SKIPPED: not in termux_hosts'; else step 'read Termux inventory group' false; fi
  finish
fi
if [ "$IS_TERMUX" != 1 ]; then
  note 'SKIPPED: Termux packages require the Termux environment'
  finish
fi

# Role defaults are overridden by group_vars/all and then host_vars, as before.
# No YAML parser is needed on a freshly bootstrapped phone without overrides.
load_overrides() {
  local file key has value rc
  for file in "$DOTFILES_DIR/group_vars/all.yml" "$DOTFILES_DIR/host_vars/$MACHINE.yml"; do
    [ -e "$file" ] || [ -L "$file" ] || continue
    [ -f "$file" ] && [ -r "$file" ] || { echo 'Cannot read Termux package configuration' >&2; return 1; }
    grep -Eq '^termux_(pkgs|npm_global|keepalive_period_ms):' "$file"; rc=$?
    case "$rc" in 0) ;; 1) continue ;; *) echo 'Cannot read Termux package configuration' >&2; return 1 ;; esac
    package_require_yq || return 1
    for key in termux_pkgs termux_npm_global; do
      has="$(yq -r "has(\"$key\")" "$file")" || return 1
      if [ "$has" = true ]; then
        package_list "$key" "$file" || return 1
        if [ "$key" = termux_pkgs ]; then TERMUX_PACKAGES=("${PACKAGE_LIST[@]}"); else TERMUX_NPM_GLOBAL=("${PACKAGE_LIST[@]}"); fi
      fi
    done
    has="$(yq -r 'has("termux_keepalive_period_ms")' "$file")" || return 1
    if [ "$has" = true ]; then
      value="$(yq -r '.termux_keepalive_period_ms' "$file")" || return 1
      TERMUX_KEEPALIVE_PERIOD_MS="$value"
    fi
  done
  [[ "$TERMUX_KEEPALIVE_PERIOD_MS" =~ ^[0-9]+$ ]]
}
update_packages() {
  local attempt
  for attempt in 1 2 3; do
    pkg update -y && return 0
    [ "$attempt" = 3 ] || sleep 5
  done
  return 1
}
install_packages() {
  local pkg rc=0
  [ "$#" != 0 ] || return 0
  pkg install -y "$@" && return 0
  for pkg in "$@"; do
    if ! pkg install -y "$pkg"; then
      echo "Termux package unavailable or installation failed: $pkg" >&2
      rc=1
    fi
  done
  return "$rc"
}
ensure_sshd() {
  local rc
  pgrep -x sshd >/dev/null 2>&1; rc=$?
  case "$rc" in 0) return 0 ;; 1) sshd ;; *) echo 'Cannot inspect Termux sshd process' >&2; return 1 ;; esac
}
pending_keepalive() {
  [[ "$1" =~ (^|[^[:alnum:]_])Pending[[:space:]]Job[[:space:]]1([^[:digit:]]|$) ]]
}
schedule_keepalive() {
  local pending
  pending="$(termux-job-scheduler -p 2>/dev/null)" || { echo 'Cannot inspect Termux scheduled jobs' >&2; return 1; }
  pending_keepalive "$pending" && return 0
  termux-job-scheduler --job-id 1 --period-ms "$TERMUX_KEEPALIVE_PERIOD_MS" --persisted true -s "$HOME/.termux/boot/start-sshd"
}

known_boot_script() {
  cmp -s "$1" "$DOTFILES_DIR/units/termux-start-sshd" || cmp -s "$1" <(printf '%s\n' \
    '#!/data/data/com.termux/files/usr/bin/sh' \
    '# Run at boot via Termux:Boot and periodically via Android'"'"'s JobScheduler.' \
    '# Termux:Boot and Termux:API are separate companion apps.' \
    'termux-wake-lock' 'sshd')
}
check_termux_packages() {
  local installed pkg line state name found
  installed="$(dpkg-query -W -f='${db:Status-Status} ${binary:Package}\n' 2>/dev/null)" || {
    echo 'Cannot inspect installed Termux packages' >&2; return 1;
  }
  for pkg in "$@"; do
    found=0
    while IFS=' ' read -r state name; do
      name="${name%%:*}"
      [ "$state" != installed ] || [ "$name" != "$pkg" ] || found=1
    done <<< "$installed"
    if [ "$found" = 0 ]; then note "WOULD install Termux package $pkg"; else note "ok    Termux package $pkg"; fi
  done
}
check_termux_boot() {
  local known=0
  if [ -f "$HOME/.termux/boot/start-sshd" ] && known_boot_script "$HOME/.termux/boot/start-sshd"; then known=1; fi
  PYTHONDONTWRITEBYTECODE=1 python3 - "$HOME/.termux/boot" "$known" <<'PY'
import os, stat, sys
directory, known = sys.argv[1:]
dest = os.path.join(directory, 'start-sshd')
try:
    try:
        info = os.stat(directory)
        directory_ok = stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o755
    except FileNotFoundError:
        directory_ok = False
    print(('ok    ' if directory_ok else 'WOULD create or chmod ') + 'Termux boot directory')
    if os.path.islink(dest) or (os.path.lexists(dest) and not os.path.isfile(dest)):
        print('Cannot replace non-regular Termux sshd boot script', file=sys.stderr)
        sys.exit(1)
    try:
        info = os.stat(dest)
        if known != '1':
            print('Cannot replace customized Termux sshd boot script', file=sys.stderr)
            sys.exit(1)
        same = stat.S_IMODE(info.st_mode) == 0o755
    except FileNotFoundError:
        same = False
    print(('ok    ' if same else 'WOULD install or chmod ') + 'Termux sshd boot script')
except OSError:
    print('Cannot inspect Termux boot files', file=sys.stderr)
    sys.exit(1)
PY
}
check_termux_sshd() {
  local rc
  pgrep -x sshd >/dev/null 2>&1; rc=$?
  case "$rc" in
    0) note 'ok    Termux sshd running' ;;
    1) note 'WOULD start Termux sshd' ;;
    *) echo 'Cannot inspect Termux sshd process' >&2; return 1 ;;
  esac
}
check_termux_keepalive() {
  local pending
  pending="$(termux-job-scheduler -p 2>/dev/null)" || { echo 'Cannot inspect Termux scheduled jobs' >&2; return 1; }
  if pending_keepalive "$pending"; then
    note 'ok    Termux sshd keep-alive job exists (period not checked by apply)'
  else
    note "WOULD schedule Termux sshd keep-alive every $TERMUX_KEEPALIVE_PERIOD_MS ms"
  fi
}
check_termux_overrides() {
  local file rc
  for file in "$DOTFILES_DIR/group_vars/all.yml" "$DOTFILES_DIR/host_vars/$MACHINE.yml"; do
    [ -e "$file" ] || [ -L "$file" ] || continue
    [ -f "$file" ] && [ -r "$file" ] || { echo 'Cannot inspect Termux package configuration' >&2; return 1; }
    grep -Eq '^termux_(pkgs|npm_global|keepalive_period_ms):' "$file"; rc=$?
    [ "$rc" -le 1 ] || { echo 'Cannot inspect Termux package configuration' >&2; return 1; }
  done
  load_overrides
}
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  note 'WOULD update Termux package cache (not inspected offline)'
  if check_termux_overrides; then
    step 'inspect Termux packages' check_termux_packages "${TERMUX_BOOTSTRAP[@]}" "${TERMUX_OPTIONAL[@]}" "${TERMUX_PACKAGES[@]}"
    for npm_package in "${TERMUX_NPM_GLOBAL[@]}"; do
      note "WOULD run npm install -g $npm_package (current registry version not inspected)"
    done
    step 'inspect Termux sshd keep-alive' check_termux_keepalive
  else
    step 'read Termux package configuration' false
  fi
  step 'inspect Termux boot files' check_termux_boot
  step 'inspect Termux sshd' check_termux_sshd
  finish
fi

step 'Termux package cache' update_packages
step 'Termux bootstrap packages' install_packages "${TERMUX_BOOTSTRAP[@]}"
soft 'Termux optional mise' install_packages "${TERMUX_OPTIONAL[@]}"
config_ok=0
if load_overrides; then
  config_ok=1
  step 'Termux packages' install_packages "${TERMUX_PACKAGES[@]}"
  for npm_package in "${TERMUX_NPM_GLOBAL[@]}"; do
    step "Termux npm package $npm_package" npm install -g "$npm_package"
  done
else
  step 'read Termux package configuration' false
fi
step 'Termux boot directory' install -d -m 0755 "$HOME/.termux/boot"
boot_ready=0
boot_script="$HOME/.termux/boot/start-sshd"
if [ -L "$boot_script" ] || { [ -e "$boot_script" ] && [ ! -f "$boot_script" ]; }; then
  echo 'Cannot replace non-regular Termux sshd boot script' >&2
  step 'Termux sshd boot script' false
elif [ -e "$boot_script" ] && ! known_boot_script "$boot_script"; then
  echo 'Cannot replace customized Termux sshd boot script' >&2
  step 'Termux sshd boot script' false
elif [ -e "$boot_script" ]; then
  if chmod 0755 "$boot_script"; then
    note 'ok    Termux sshd boot script'
    boot_ready=1
  else
    step 'Termux sshd boot script' false
  fi
elif install_if_changed "$DOTFILES_DIR/units/termux-start-sshd" "$boot_script" 0755; then
  note 'ok    Termux sshd boot script'
  boot_ready=1
else
  step 'Termux sshd boot script' false
fi
step 'Termux sshd running' ensure_sshd
if [ "$config_ok" = 1 ] && [ "$boot_ready" = 1 ]; then
  step 'Termux sshd keep-alive' schedule_keepalive
fi
finish
