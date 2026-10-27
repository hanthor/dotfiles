#!/usr/bin/env bash
set -uo pipefail
# The session must not be printed even when the caller enables shell tracing.
set +x
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=units/platform-config.bash
. "$DOTFILES_DIR/units/platform-config.bash"

if [ "$IS_TERMUX" = 1 ]; then
  note 'SKIPPED: Android Tailscale is managed outside unprivileged Termux'
  finish
fi
root="${DOTFILES_SYSTEM_ROOT:-}"
retired=0
case "$MACHINE" in matrix|telengana) retired=1 ;; esac
routes="$(host_var tailscale_advertise_routes)"
accept_dns="$(host_var tailscale_accept_dns true)"
operator="$(host_var tailscale_operator)"
domain="$(host_var tailscale_domain)"
if [ -z "$domain" ]; then
  domain="$(sed -n 's/^tailscale_domain:[[:space:]]*\([^#]*[^#[:space:]]\).*/\1/p' "$DOTFILES_DIR/group_vars/all.yml" 2>/dev/null | head -n1)"
  domain="${domain//[\"\']/}"
fi
resolved_changed=0
sysctl_changed=0

check_tailscale_files() {
  local connected="$1" resolved_active="$2"
  PYTHONDONTWRITEBYTECODE=1 python3 - "$root" "$accept_dns" "$resolved_active" "$connected" "$retired" <<'PY'
import os, stat, sys
root, accept_dns, active, connected, retired = sys.argv[1:]
def path(name):
    return root + name
def directory(name):
    try:
        info = os.stat(path(name))
        return stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o755
    except FileNotFoundError:
        return False
def content(name, expected):
    try:
        filename = path(name)
        info = os.lstat(filename)
        if not stat.S_ISREG(info.st_mode):
            return False
        with open(filename, 'rb') as f:
            same = f.read() == expected
        return same and stat.S_IMODE(info.st_mode) == 0o644 and info.st_uid == 0 and info.st_gid == 0
    except FileNotFoundError:
        return False
def report(label, good):
    print(('ok    ' if good else 'WOULD configure ') + label)
try:
    report('Tailscale resolved directory', directory('/etc/systemd/resolved.conf.d'))
    resolved = not content('/etc/systemd/resolved.conf.d/ipv6-stub.conf', b'[Resolve]\nDNSStubListenerExtra=::1\n')
    report('Tailscale resolved configuration', not resolved)
    if accept_dns != 'false' and active == 'active':
        try:
            linked = os.readlink(path('/etc/resolv.conf')) == '/run/systemd/resolve/stub-resolv.conf'
        except FileNotFoundError:
            linked = False
        except OSError as e:
            if e.errno != 22: raise
            linked = False
        report('Tailscale resolver link', linked)
        resolved = resolved or not linked
    report('Tailscale sysctl directory', directory('/etc/sysctl.d'))
    sysctl = not content('/etc/sysctl.d/99-tailscale.conf', b'net.ipv4.conf.all.rp_filter = 2\nnet.ipv4.conf.default.rp_filter = 2\nnet.ipv4.ip_forward = 1\nnet.ipv6.conf.all.forwarding = 1\n')
    report('Tailscale sysctl configuration', not sysctl)
    if resolved:
        print('SKIPPED: resolved restart on retired VPS' if retired == '1' else 'WOULD restart systemd-resolved')
    if sysctl:
        print('WOULD apply Tailscale sysctls')
    if connected == '1' and accept_dns == 'false':
        report('Tailscale static DNS', content('/etc/resolv.conf', b'nameserver 1.1.1.1\nnameserver 8.8.8.8\n'))
except OSError:
    print('Cannot inspect Tailscale system files', file=sys.stderr)
    sys.exit(1)
PY
}
check_tailscale_prefs() {
  local prefs user
  prefs="$(tailscale debug prefs 2>/dev/null)" || { echo 'Cannot inspect Tailscale preferences' >&2; return 1; }
  user="${USER:-$(id -un)}"
  PYTHONDONTWRITEBYTECODE=1 python3 -c '
import json, sys
try:
    raw = sys.stdin.read()
    prefs = json.loads(raw)
    if not isinstance(prefs, dict): raise ValueError()
    hostname, routes, desktop, user = sys.argv[1:]
    print(("ok    " if prefs.get("Hostname", "") == hostname else "WOULD set ") + "Tailscale hostname")
    if routes:
        print(("ok    " if routes in raw else "WOULD configure ") + "Tailscale advertised routes")
    if desktop == "1":
        print(("ok    " if prefs.get("OperatorUser", "") == user else "WOULD set ") + "Tailscale desktop operator")
except (ValueError, TypeError):
    print("Cannot parse Tailscale preferences", file=sys.stderr)
    sys.exit(1)
' "$MACHINE" "$routes" "$1" "$user" <<< "$prefs"
}
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  for config in "$DOTFILES_DIR/host_vars/$MACHINE.yml" "$DOTFILES_DIR/group_vars/all.yml"; do
    if [ -e "$config" ] || [ -L "$config" ]; then
      [ -f "$config" ] && [ -r "$config" ] || step 'inspect Tailscale configuration' false
    fi
  done
  if [ -z "$domain" ]; then note 'PARTIAL: Tailscale domain is unset; joining requires a configured domain'; fi
  resolved_active=inactive
  if [ "$accept_dns" != false ]; then
    resolved_active="$(systemctl is-active systemd-resolved 2>/dev/null)"; rc=$?
    case "$resolved_active:$rc" in
      active:0|reloading:0|refreshing:0|inactive:3|failed:3|activating:3|deactivating:3) ;;
      unknown:4)
        load_state="$(systemctl show -p LoadState --value systemd-resolved 2>/dev/null)" || load_state=''
        [ "$load_state" = not-found ] || step 'inspect systemd-resolved state' false ;;
      *) step 'inspect systemd-resolved state' false ;;
    esac
  fi
  connected=0
  if command -v tailscale >/dev/null 2>&1; then
    status="$(tailscale status --json 2>/dev/null)"
    if [ "$?" = 0 ] && backend="$(PYTHONDONTWRITEBYTECODE=1 python3 -c '
import json, sys
try:
    value = json.load(sys.stdin)["BackendState"]
    if value not in ("Running", "NeedsLogin", "NeedsMachineAuth", "Stopped", "Starting", "NoState"): raise ValueError()
    print(value)
except (ValueError, KeyError, TypeError):
    sys.exit(1)
' <<< "$status")"; then
      if [ "$backend" = Running ]; then connected=1
      elif [ "$retired" = 1 ]; then note 'SKIPPED: Tailscale installation and rejoin on retired VPS'
      else note "WOULD join tailnet (Tailscale state: $backend; credentials not inspected)"; fi
    else
      step 'inspect Tailscale status' false
    fi
  elif [ "$retired" = 1 ]; then
    note 'SKIPPED: Tailscale installation and rejoin on retired VPS'
  else
    note 'WOULD install Tailscale and join tailnet (credentials not inspected)'
  fi
  step 'inspect Tailscale system files' check_tailscale_files "$connected" "$resolved_active"
  if [ "$connected" = 1 ]; then
    desktop=0
    if platform_desktop; then desktop=1; else
      rc=$?; [ "$rc" = 1 ] || step 'read desktop inventory group' false
    fi
    step 'inspect Tailscale preferences' check_tailscale_prefs "$desktop"
    if [ "$desktop" = 1 ] && [ "$retired" = 0 ]; then
      note 'WOULD configure Tailscale systray, reload user systemd, and enable/start systray service'
    fi
  fi
  finish
fi

tmp="$(mktemp -d)" || { step 'create Tailscale staging directory' false; finish; }
trap 'rm -rf "$tmp"' EXIT

# Replace system files atomically, without following a pre-existing symlink.
install_system_file() {
  local src="$1" dest="$2" flag="$3" state staged
  state="$(stat -c '%a:%u:%g' "$dest" 2>/dev/null)" || state=''
  if [ ! -L "$dest" ] && cmp -s "$src" "$dest" && [ "$state" = '644:0:0' ]; then return 0; fi
  staged="$(platform_root mktemp "$(dirname "$dest")/.dotfiles.XXXXXXXX")" || return 1
  if ! platform_root install -m 0644 -o root -g root "$src" "$staged" || ! platform_root mv -fT "$staged" "$dest"; then
    platform_root rm -f "$staged"
    return 1
  fi
  case "$flag" in resolved) resolved_changed=1 ;; sysctl) sysctl_changed=1 ;; esac
}
configure_resolved() {
  platform_root install -d -m 0755 "$root/etc/systemd/resolved.conf.d" || return 1
  printf '[Resolve]\nDNSStubListenerExtra=::1\n' > "$tmp/resolved" || return 1
  install_system_file "$tmp/resolved" "$root/etc/systemd/resolved.conf.d/ipv6-stub.conf" resolved
}
configure_resolv_link() {
  local active
  [ "$accept_dns" != false ] || return 0
  active="$(systemctl is-active systemd-resolved 2>/dev/null)" || :
  [ "$active" = active ] || return 0
  if [ "$(readlink "$root/etc/resolv.conf" 2>/dev/null)" = /run/systemd/resolve/stub-resolv.conf ]; then return 0; fi
  platform_root ln -sfn /run/systemd/resolve/stub-resolv.conf "$root/etc/resolv.conf" || return 1
  resolved_changed=1
}
configure_sysctl() {
  platform_root install -d -m 0755 "$root/etc/sysctl.d" || return 1
  printf '%s\n' 'net.ipv4.conf.all.rp_filter = 2' 'net.ipv4.conf.default.rp_filter = 2' 'net.ipv4.ip_forward = 1' 'net.ipv6.conf.all.forwarding = 1' > "$tmp/sysctl" || return 1
  install_system_file "$tmp/sysctl" "$root/etc/sysctl.d/99-tailscale.conf" sysctl
}
configure_routes() {
  local prefs args=()
  [ -n "$routes" ] || return 0
  prefs="$(tailscale debug prefs 2>/dev/null)" || :
  case "$prefs" in *"$routes"*) return 0 ;; esac
  args=(up "--hostname=$MACHINE" "--advertise-routes=$routes")
  [ "$accept_dns" != false ] || args+=(--accept-dns=false)
  [ -z "$operator" ] || args+=("--operator=$operator")
  platform_root tailscale "${args[@]}"
}
configure_static_dns() {
  [ "$accept_dns" = false ] || return 0
  printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > "$tmp/resolv" || return 1
  install_system_file "$tmp/resolv" "$root/etc/resolv.conf" none
}
install_tailscale() {
  command -v tailscale >/dev/null 2>&1 && return 0
  if command -v ujust >/dev/null 2>&1; then
    ujust install-tailscale
  else
    curl -fsSL --max-time 60 https://tailscale.com/install.sh -o "$tmp/install.sh" &&
      [ -s "$tmp/install.sh" ] && platform_root sh "$tmp/install.sh"
  fi
}
join_tailnet() {
  local session mode
  session="$(bw_session)"
  if [ -z "$session" ]; then
    note 'PARTIAL: Tailscale not connected; vault locked or secrets disabled'
    return 0
  fi
  [ -n "$domain" ] || { echo 'tailscale_domain is missing' >&2; return 1; }
  mode=sudo
  [ "$(id -u)" != 0 ] || mode=root
  BW_SESSION="$session" python3 "$DOTFILES_DIR/units/tailscale-connect.py" "$MACHINE" "$domain" "$mode" || return 1
  if [ -n "$routes" ]; then
    platform_root tailscale up "--advertise-routes=$routes" --reset=false || return 1
  fi
}

step 'Tailscale resolved configuration' configure_resolved
step 'Tailscale resolver link' configure_resolv_link
step 'Tailscale sysctl configuration' configure_sysctl
if [ "$resolved_changed" = 1 ]; then
  if [ "$retired" = 1 ]; then note 'SKIPPED: resolved restart on retired VPS';
  else soft 'restart systemd-resolved' platform_root systemctl restart systemd-resolved; fi
fi
if [ "$sysctl_changed" = 1 ]; then step 'apply Tailscale sysctls' platform_root sysctl -p "$root/etc/sysctl.d/99-tailscale.conf"; fi

if tailscale status >/dev/null 2>&1; then
  step 'Tailscale advertised routes' configure_routes
  step 'Tailscale hostname' platform_root tailscale set "--hostname=$MACHINE"
  step 'Tailscale static DNS' configure_static_dns
  if platform_desktop; then
    soft 'Tailscale desktop operator' platform_root tailscale set "--operator=${USER:-$(id -un)}"
    if [ "$retired" = 0 ]; then
      soft 'Tailscale systray configuration' tailscale configure systray --enable-startup=systemd
      soft 'Tailscale systray service' systemctl --user daemon-reload
      soft 'Tailscale systray start' systemctl --user enable --now tailscale-systray
    fi
  else
    desktop_rc=$?
    [ "$desktop_rc" = 1 ] || step 'read desktop inventory group' false
  fi
else
  if [ "$retired" = 1 ]; then
    note 'SKIPPED: Tailscale installation and rejoin on retired VPS'
  else
    step 'Tailscale installation' install_tailscale
    if command -v tailscale >/dev/null 2>&1; then step 'Tailscale join' join_tailnet
    else step 'Tailscale binary available' false; fi
  fi
fi
finish
