#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ]; then
  note "SKIPPED: Tailscale certificates excluded on this host"
  finish
fi
settings=$(python3 "$DOTFILES_DIR/units/proxy-inventory.py" cert "$DOTFILES_DIR/inventory.yml" "$MACHINE") || { step "resolve certificate inventory settings" false; finish; }
case "${settings%%$'\n'*}" in
  skip) note "SKIPPED: Tailscale certificates excluded on this host"; finish ;;
  run) domain=${settings#*$'\n'} ;;
  *) step "resolve certificate inventory settings" false; finish ;;
esac
as_root() { if [ "$EUID" = 0 ]; then "$@"; else sudo -n "$@"; fi; }
if [[ ! "$MACHINE" =~ ^[[:alnum:]_.-]+$ || ! "$domain" =~ ^[[:alnum:]_.-]+$ ]]; then
  step "validate certificate hostname and domain" false
  finish
fi
# Do not follow user-supplied symlinks or overwrite special files as root.
for path in /etc/ssl/tailscale /etc/ssl/tailscale/cert.pem /etc/ssl/tailscale/key.pem; do
  if as_root test -L "$path"; then step "refuse symlink certificate path $path" false; finish; fi
done
if as_root test -e /etc/ssl/tailscale && ! as_root test -d /etc/ssl/tailscale; then
  step "refuse non-directory certificate path /etc/ssl/tailscale" false
  finish
fi
for path in /etc/ssl/tailscale/cert.pem /etc/ssl/tailscale/key.pem; do
  if as_root test -e "$path" && ! as_root test -f "$path"; then step "refuse non-regular certificate path $path" false; finish; fi
done
cert_identity_ok() {
  local cert_pub key_pub host_check
  host_check=$(LC_ALL=C as_root openssl x509 -checkhost "$MACHINE.$domain" -noout -in /etc/ssl/tailscale/cert.pem 2>/dev/null) || return 1
  [ "$host_check" = "Hostname $MACHINE.$domain does match certificate" ] || return 1
  cert_pub=$(as_root openssl x509 -pubkey -noout -in /etc/ssl/tailscale/cert.pem 2>/dev/null) || return 1
  key_pub=$(as_root openssl pkey -pubout -passin pass: -in /etc/ssl/tailscale/key.pem 2>/dev/null) || return 1
  [ -n "$cert_pub" ] && [ "$cert_pub" = "$key_pub" ]
}
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if [ "$EUID" != 0 ] && ! sudo -n true; then step "noninteractive root access" false; finish; fi
  tmp=$(mktemp -d) || { step "create certificate temporary directory" false; finish; }
  trap 'rm -rf "$tmp"' EXIT
  if as_root test -e /etc/ssl/tailscale; then
    mode=$(as_root stat -c '%a:%u:%g' /etc/ssl/tailscale) || { step "inspect certificate directory" false; mode=; }
    [ -z "$mode" ] || { if as_root test -d /etc/ssl/tailscale && [ "$mode" = '755:0:0' ]; then note "ok    certificate directory"; else note "would set certificate directory ownership and permissions"; fi; }
  else note "would create certificate directory"; fi
  renew=0
  if ! as_root test -e /etc/ssl/tailscale/cert.pem; then
    renew=1
    note "would provision Tailscale certificate for $MACHINE.$domain"
  elif ! as_root openssl x509 -noout -in /etc/ssl/tailscale/cert.pem >/dev/null 2>&1; then
    step "inspect Tailscale certificate" false
  elif ! as_root test -s /etc/ssl/tailscale/key.pem; then
    renew=1
    note "would renew Tailscale certificate for $MACHINE.$domain (private key missing or empty)"
  elif as_root openssl x509 -checkend 2592000 -noout -in /etc/ssl/tailscale/cert.pem >/dev/null 2>&1; then
    if cert_identity_ok; then
      note "ok    certificate valid for at least 30 days and matches hostname and private key"
    else
      step "verify certificate hostname and private key (existing pair preserved)" false
    fi
  else
    renew=1
    note "would renew Tailscale certificate for $MACHINE.$domain"
  fi
  cert_check_mode() {
    local path=$1 expected=$2 mode
    if as_root test -e "$path"; then
      if mode=$(as_root stat -c '%a:%u:%g' "$path"); then
        [ "$mode" = "$expected:0:0" ] && note "ok    permissions $path" || note "would set ownership and permissions on $path"
      else step "inspect permissions $path" false; fi
    elif [ "$renew" = 1 ]; then
      note "would set ownership and permissions on newly provisioned $path"
    else
      step "missing $path (apply cannot set its permissions)" false
    fi
  }
  cert_check_mode /etc/ssl/tailscale/cert.pem 644
  cert_check_mode /etc/ssl/tailscale/key.pem 640
  cert_check_file() {
    local src=$1 dest=$2 expected=${3:-644} mode rc
    [ -r "$src" ] || { step "read $src" false; return; }
    if ! as_root test -e "$dest" && ! as_root test -L "$dest"; then note "would deploy $dest"; return; fi
    mode=$(as_root stat -c '%a:%u:%g' "$dest") || { step "inspect $dest" false; return; }
    as_root cmp -s "$src" "$dest"; rc=$?
    case "$rc" in
      0) [ "$mode" = "$expected:0:0" ] && note "ok    $dest" || note "would set ownership and permissions on $dest" ;;
      1) note "would deploy $dest" ;;
      *) step "compare $dest" false ;;
    esac
  }
  cert_check_file "$DOTFILES_DIR/units/tailscale-cert/renew.sh" /etc/systemd/system/tailscale-cert-renew.sh 755
  if python3 "$DOTFILES_DIR/units/service-templates.py" cert "$DOTFILES_DIR/units/tailscale-cert/tailscale-cert-renew.service.j2" "$MACHINE" "$domain" > "$tmp/service" && [ -s "$tmp/service" ]; then
    cert_check_file "$tmp/service" /etc/systemd/system/tailscale-cert-renew.service
  else step "render certificate renewal service" false; fi
  cert_check_file "$DOTFILES_DIR/units/tailscale-cert/tailscale-cert-renew.timer" /etc/systemd/system/tailscale-cert-renew.timer
  state=$(as_root systemctl show tailscale-cert-renew.timer --property=LoadState --property=ActiveState --property=UnitFileState 2>/dev/null); rc=$?
  if { [ "$rc" != 0 ] && [[ "$state" != *'LoadState=not-found'* ]]; } || [[ "$state" != *'LoadState='* || "$state" != *'ActiveState='* ]]; then
    step "inspect certificate renewal timer" false
  elif [[ "$state" == *'LoadState=not-found'* ]]; then
    note "would reload systemd and enable and start certificate renewal timer"
  elif [[ "$state" != *'LoadState=loaded'* || "$state" != *'UnitFileState='* ]]; then
    step "inspect certificate renewal timer" false
  else
    [[ "$state" == *'ActiveState=active'* ]] || note "would start certificate renewal timer"
    [[ "$state" == *'UnitFileState=enabled'* ]] || note "would enable certificate renewal timer"
  fi
  finish
fi
if ! as_root install -d -m 0755 -o root -g root /etc/ssl/tailscale; then
  step "create Tailscale certificate directory" false
  finish
fi
if ! as_root test -s /etc/ssl/tailscale/key.pem || ! as_root openssl x509 -checkend 2592000 -noout -in /etc/ssl/tailscale/cert.pem >/dev/null 2>&1; then
  if ! as_root bash "$DOTFILES_DIR/units/tailscale-cert/renew.sh" /etc/ssl/tailscale "$MACHINE.$domain"; then
    step "provision Tailscale certificate" false
    finish
  fi
  note "ok    provision Tailscale certificate"
else
  if ! cert_identity_ok; then
    step "verify certificate hostname and private key (existing pair preserved)" false
    finish
  fi
fi
set_cert_mode() {
  as_root chown root:root "$1" && as_root chmod "$2" "$1"
}
step "set certificate permissions" set_cert_mode /etc/ssl/tailscale/cert.pem 0644
step "set private key permissions" set_cert_mode /etc/ssl/tailscale/key.pem 0640

tmp=$(mktemp -d) || { step "create certificate temporary directory" false; finish; }
trap 'rm -rf "$tmp"' EXIT
install_root_file() {
  local src="$1" dest="$2" expected="${3:-644}" mode
  mode=$(as_root stat -c '%a:%u:%g' "$dest" 2>/dev/null || true)
  if as_root cmp -s "$src" "$dest" && [ "$mode" = "$expected:0:0" ]; then return 0; fi
  as_root install -m "0$expected" -o root -g root "$src" "$dest"
}
if ! install_root_file "$DOTFILES_DIR/units/tailscale-cert/renew.sh" /etc/systemd/system/tailscale-cert-renew.sh 755; then
  step "deploy certificate renewal helper" false
  finish
fi
note "ok    deploy certificate renewal helper"
service_ok=0
timer_ok=0
if python3 "$DOTFILES_DIR/units/service-templates.py" cert "$DOTFILES_DIR/units/tailscale-cert/tailscale-cert-renew.service.j2" "$MACHINE" "$domain" > "$tmp/tailscale-cert-renew.service" &&
   [ -s "$tmp/tailscale-cert-renew.service" ] &&
   install_root_file "$tmp/tailscale-cert-renew.service" /etc/systemd/system/tailscale-cert-renew.service; then
  service_ok=1
  note "ok    deploy certificate renewal service"
else
  step "deploy certificate renewal service" false
fi
if install_root_file "$DOTFILES_DIR/units/tailscale-cert/tailscale-cert-renew.timer" /etc/systemd/system/tailscale-cert-renew.timer; then
  timer_ok=1
  note "ok    deploy certificate renewal timer"
else
  step "deploy certificate renewal timer" false
fi
if [ "$service_ok" = 1 ] && [ "$timer_ok" = 1 ]; then
  if as_root systemctl daemon-reload; then
    step "enable and start certificate renewal timer" as_root systemctl enable --now tailscale-cert-renew.timer
  else
    step "reload systemd for certificate renewal" false
  fi
fi
finish
