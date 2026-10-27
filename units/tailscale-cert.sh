#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ] || skipped_by_profile skip_tailscale_cert; then
  note "SKIPPED: Tailscale certificates excluded on this host"
  finish
fi
if ! command -v yq >/dev/null 2>&1; then
  step "check certificate VPS membership (yq required)" false
  finish
fi
vps=$(MACHINE="$MACHINE" yq '.all.children.vps.hosts | has(strenv(MACHINE))' "$DOTFILES_DIR/inventory.yml") || { step "check certificate VPS membership" false; finish; }
case "$vps" in
  true) note "SKIPPED: Tailscale certificates excluded on VPS"; finish ;;
  false) ;;
  *) step "check certificate VPS membership" false; finish ;;
esac
as_root() { if [ "$EUID" = 0 ]; then "$@"; else sudo -n "$@"; fi; }
# Host variables override the shared group domain, as in the playbook.
domain=""
if [ -f "$DOTFILES_DIR/host_vars/$MACHINE.yml" ]; then
  domain=$(yq -r '.tailscale_domain // ""' "$DOTFILES_DIR/host_vars/$MACHINE.yml") || { step "read host certificate domain" false; finish; }
fi
if [ -z "$domain" ]; then
  domain=$(yq -r '.tailscale_domain // ""' "$DOTFILES_DIR/group_vars/all.yml") || { step "read certificate domain" false; finish; }
fi
if [[ ! "$MACHINE" =~ ^[[:alnum:]_.-]+$ || ! "$domain" =~ ^[[:alnum:]_.-]+$ ]]; then
  step "validate certificate hostname and domain" false
  finish
fi
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
  elif as_root openssl x509 -checkend 2592000 -noout -in /etc/ssl/tailscale/cert.pem >/dev/null 2>&1; then
    note "ok    certificate valid for at least 30 days"
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
    local src=$1 dest=$2 mode rc
    [ -r "$src" ] || { step "read $src" false; return; }
    if ! as_root test -e "$dest" && ! as_root test -L "$dest"; then note "would deploy $dest"; return; fi
    mode=$(as_root stat -c '%a:%u:%g' "$dest") || { step "inspect $dest" false; return; }
    as_root cmp -s "$src" "$dest"; rc=$?
    case "$rc" in
      0) [ "$mode" = '644:0:0' ] && note "ok    $dest" || note "would set ownership and permissions on $dest" ;;
      1) note "would deploy $dest" ;;
      *) step "compare $dest" false ;;
    esac
  }
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
step "create Tailscale certificate directory" as_root install -d -m 0755 -o root -g root /etc/ssl/tailscale
if ! as_root openssl x509 -checkend 2592000 -noout -in /etc/ssl/tailscale/cert.pem >/dev/null 2>&1; then
  step "provision Tailscale certificate" as_root tailscale cert --cert-file /etc/ssl/tailscale/cert.pem --key-file /etc/ssl/tailscale/key.pem --min-validity 720h "$MACHINE.$domain"
fi
set_cert_mode() {
  as_root chown root:root "$1" && as_root chmod "$2" "$1"
}
step "set certificate permissions" set_cert_mode /etc/ssl/tailscale/cert.pem 0644
step "set private key permissions" set_cert_mode /etc/ssl/tailscale/key.pem 0640

tmp=$(mktemp -d) || { step "create certificate temporary directory" false; finish; }
trap 'rm -rf "$tmp"' EXIT
install_root_file() {
  local src="$1" dest="$2" mode
  mode=$(as_root stat -c '%a:%u:%g' "$dest" 2>/dev/null || true)
  if as_root cmp -s "$src" "$dest" && [ "$mode" = '644:0:0' ]; then return 0; fi
  as_root install -m 0644 -o root -g root "$src" "$dest"
}
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
