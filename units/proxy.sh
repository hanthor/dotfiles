#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ]; then
  note "SKIPPED: proxy excluded on this host"
  finish
fi
settings=$(python3 "$DOTFILES_DIR/units/proxy-inventory.py" proxy "$DOTFILES_DIR/inventory.yml" "$MACHINE") || { step "resolve proxy inventory settings" false; finish; }
case "${settings%%$'\n'*}" in
  skip) note "SKIPPED: proxy excluded on this host"; finish ;;
  run) services=${settings#*$'\n'} ;;
  *) step "resolve proxy inventory settings" false; finish ;;
esac

as_root() { if [ "$EUID" = 0 ]; then "$@"; else sudo -n "$@"; fi; }
tmp=$(mktemp -d) || { step "create proxy temporary directory" false; finish; }
trap 'rm -rf "$tmp"' EXIT
changed=0
install_root_file() {
  local src="$1" dest="$2" mode
  mode=$(as_root stat -c '%a:%u:%g' "$dest" 2>/dev/null || true)
  if as_root cmp -s "$src" "$dest" && [ "$mode" = '644:0:0' ]; then return 0; fi
  as_root install -m 0644 -o root -g root "$src" "$dest" || return 1
  changed=1
}
render_caddyfile() {
  printf '%s\n' "$services" > "$tmp/services.json" || return 1
  python3 "$DOTFILES_DIR/units/service-templates.py" proxy "$DOTFILES_DIR/units/proxy/Caddyfile.j2" "$tmp/services.json" > "$tmp/Caddyfile"
}
inspect_serve() {
  as_root tailscale status --json > "$tmp/status.json" || return 1
  as_root tailscale serve status --json > "$tmp/serve.json" || return 1
  python3 "$DOTFILES_DIR/units/proxy-serve.py" "$tmp/status.json" "$tmp/serve.json"
}
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if [ "$EUID" != 0 ] && ! sudo -n true; then step "noninteractive root access" false; finish; fi
  proxy_check_dir() {
    local dir=$1 mode
    if as_root test -e "$dir"; then
      if mode=$(as_root stat -c '%a:%u:%g' "$dir"); then
        if as_root test -d "$dir" && [ "$mode" = '755:0:0' ]; then note "ok    directory $dir"; else note "would create or set ownership and permissions on $dir"; fi
      else step "inspect directory $dir" false; fi
    else note "would create directory $dir"; fi
  }
  proxy_check_file() {
    local src=$1 dest=$2 mode rc
    [ -r "$src" ] || { step "read $src" false; return; }
    if ! as_root test -e "$dest" && ! as_root test -L "$dest"; then note "would deploy $dest and restart Caddy"; return; fi
    mode=$(as_root stat -c '%a:%u:%g' "$dest") || { step "inspect $dest" false; return; }
    as_root cmp -s "$src" "$dest"; rc=$?
    case "$rc" in
      0) [ "$mode" = '644:0:0' ] && note "ok    $dest" || note "would set ownership and permissions on $dest and restart Caddy" ;;
      1) note "would deploy $dest and restart Caddy" ;;
      *) step "compare $dest" false ;;
    esac
  }
  proxy_check_dir /etc/caddy
  proxy_check_dir /etc/containers/systemd
  if render_caddyfile; then proxy_check_file "$tmp/Caddyfile" /etc/caddy/Caddyfile; else step "render Caddyfile" false; fi
  proxy_check_file "$DOTFILES_DIR/units/proxy/caddy.container" /etc/containers/systemd/caddy.container
  state=$(as_root systemctl show caddy.service --property=LoadState --property=ActiveState --property=UnitFileState 2>/dev/null); rc=$?
  if { [ "$rc" != 0 ] && [[ "$state" != *'LoadState=not-found'* ]]; } || [[ "$state" != *'LoadState='* || "$state" != *'ActiveState='* ]]; then
    step "inspect Caddy service" false
  elif [[ "$state" == *'LoadState=not-found'* ]]; then
    note "would reload systemd and enable and start Caddy"
  elif [[ "$state" != *'LoadState=loaded'* || "$state" != *'UnitFileState='* ]]; then
    step "inspect Caddy service" false
  else
    [[ "$state" == *'ActiveState=active'* ]] || note "would start Caddy"
    case "$state" in *'UnitFileState=enabled'*|*'UnitFileState=generated'*) ;; *) note "would enable Caddy" ;; esac
  fi
  if serve=$(inspect_serve); then
    case "$serve" in
      true) note "ok    Tailscale serve target" ;;
      false) note "would point Tailscale serve at Caddy" ;;
      *) step "inspect Tailscale serve status" false ;;
    esac
  else step "inspect Tailscale serve status" false; fi
  finish
fi
step "create Caddy directories" as_root install -d -m 0755 -o root -g root /etc/caddy /etc/containers/systemd
caddy_ok=0
quadlet_ok=0
if render_caddyfile; then
  if install_root_file "$tmp/Caddyfile" /etc/caddy/Caddyfile; then
    caddy_ok=1
    note "ok    deploy Caddyfile"
  else
    step "deploy Caddyfile" false
  fi
else
  step "render Caddyfile" false
fi
if install_root_file "$DOTFILES_DIR/units/proxy/caddy.container" /etc/containers/systemd/caddy.container; then
  quadlet_ok=1
  note "ok    deploy Caddy quadlet"
else
  step "deploy Caddy quadlet" false
fi
# Do not switch traffic or restart a working service after a partial deploy.
if [ "$caddy_ok" = 0 ] || [ "$quadlet_ok" = 0 ]; then
  note "PARTIAL: Caddy activation skipped after a configuration failure"
  finish
fi
if ! as_root systemctl daemon-reload; then
  step "reload systemd for Caddy" false
  finish
fi
if [ "$changed" = 1 ]; then
  if as_root systemctl restart caddy.service; then
    note "ok    restart Caddy after configuration change"
  else
    step "restart Caddy after configuration change" false
    finish
  fi
fi
if as_root systemctl enable --now caddy.service; then
  note "ok    enable and start Caddy"
else
  step "enable and start Caddy" false
  finish
fi
if ! serve=$(inspect_serve); then
  step "inspect Tailscale serve status" false
  finish
fi
if [ "$serve" = false ]; then
  # --bg replaces the existing default HTTPS handler, including the old
  # direct homepage target; turning 443 off afterward would remove the new one.
  step "point Tailscale serve at Caddy" as_root tailscale serve --bg http://127.0.0.1:9000
elif [ "$serve" != true ]; then
  step "inspect Tailscale serve status" false
fi
finish
