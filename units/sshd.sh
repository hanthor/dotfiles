#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=units/platform-config.bash
. "$DOTFILES_DIR/units/platform-config.bash"
host_file="$DOTFILES_DIR/host_vars/$MACHINE.yml"
if { [ -e "$host_file" ] || [ -L "$host_file" ]; } && { [ ! -f "$host_file" ] || [ ! -r "$host_file" ]; }; then
  step 'read sshd host configuration' false
  finish
fi

root="${DOTFILES_SYSTEM_ROOT:-}"
dir="$root/etc/ssh/sshd_config.d"
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  parent="$root/etc/ssh"
  if [ -e "$parent" ] && { [ ! -d "$parent" ] || [ ! -x "$parent" ]; }; then
    step 'inspect sshd configuration directory' false
    finish
  fi
fi
if [ ! -d "$dir" ]; then
  note 'SKIPPED: sshd drop-in directory is absent'
  finish
fi
if [ "${UNITS_CHECK:-0}" = 1 ] && { [ ! -r "$dir" ] || [ ! -x "$dir" ]; }; then
  step 'inspect sshd drop-in directory' false
  finish
fi
emit_sshd_acceptenv() { printf 'AcceptEnv BW_SESSION BW_CLIENTID BW_CLIENTSECRET\n'; }
emit_sshd_hardening() {
  cat <<'EOF'
# Managed by dotfiles (sshd role, sshd_harden)
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
X11Forwarding no
MaxAuthTries 3
LoginGraceTime 30
EOF
}

if [ "${UNITS_CHECK:-0}" = 1 ]; then
  changed=0
  inspect_dropin() {
    local dest="$1" generator="$2" validate="$3" state rc
    if [ -L "$dest" ] || [ ! -e "$dest" ]; then
      changed=1
    elif [ ! -f "$dest" ]; then
      echo "Cannot replace non-file sshd drop-in: $dest" >&2
      return 1
    else
      state="$(stat -c '%a:%u:%g' "$dest")" || return 1
      if "$generator" | cmp -s - "$dest"; then
        if [ "$state" = '644:0:0' ]; then
          note "ok    sshd drop-in: $dest"
          return 0
        fi
      else
        rc=$?
        if [ "$rc" -ne 1 ]; then echo "Cannot read sshd drop-in: $dest" >&2; return 1; fi
      fi
      changed=1
    fi
    if [ "$validate" = 1 ]; then note "would validate sshd drop-in: $dest"; fi
    note "would install sshd drop-in: $dest"
  }
  step 'inspect sshd AcceptEnv drop-in' inspect_dropin "$dir/99-bw-env.conf" emit_sshd_acceptenv 0
  if [ "$(host_var sshd_harden false)" = true ]; then
    step 'inspect sshd hardening drop-in' inspect_dropin "$dir/10-hardening.conf" emit_sshd_hardening 1
  fi
  if [ "$changed" = 1 ]; then
    if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ]; then
      note 'SKIPPED: sshd reload on retired VPS'
    else
      note 'would reload sshd after changes'
    fi
  fi
  finish
fi
tmp="$(mktemp -d)" || { step 'create sshd staging directory' false; finish; }
trap 'rm -rf "$tmp"' EXIT
changed=0

install_dropin() {
  local candidate="$1" dest="$2" validate="$3" state staged
  state="$(stat -c '%a:%u:%g' "$dest" 2>/dev/null)" || state=''
  if [ ! -L "$dest" ] && cmp -s "$candidate" "$dest" && [ "$state" = '644:0:0' ]; then return 0; fi
  if [ "$validate" = 1 ]; then
    platform_root /usr/sbin/sshd -t -f "$candidate" || return 1
  fi
  staged="$(platform_root mktemp "$dir/.dotfiles.XXXXXXXX")" || return 1
  if ! platform_root install -m 0644 -o root -g root "$candidate" "$staged" || ! platform_root mv -fT "$staged" "$dest"; then
    platform_root rm -f "$staged"
    return 1
  fi
  changed=1
}

emit_sshd_acceptenv > "$tmp/bw-env"
soft 'sshd AcceptEnv drop-in' install_dropin "$tmp/bw-env" "$dir/99-bw-env.conf" 0
if [ "$(host_var sshd_harden false)" = true ]; then
  emit_sshd_hardening > "$tmp/hardening"
  step 'sshd validated hardening drop-in' install_dropin "$tmp/hardening" "$dir/10-hardening.conf" 1
fi

if [ "$changed" = 1 ]; then
  if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ]; then
    note 'SKIPPED: sshd reload on retired VPS'
  else
    service=sshd
    if [ -r "$root/etc/os-release" ]; then
      os_id=''; os_like=''
      # shellcheck source=/dev/null
      . "$root/etc/os-release"
      os_id="${ID:-}"; os_like="${ID_LIKE:-}"
      case " $os_id $os_like " in *' debian '*|*' ubuntu '*) service=ssh ;; esac
    fi
    soft 'reload sshd' platform_root systemctl reload "$service"
  fi
fi
finish
