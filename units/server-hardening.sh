#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

hardening_main() {
  local server vps memberships rc changed=0 swap_output ufw_output pro_output
  local -a rootcmd=()
  case "$MACHINE" in matrix|telengana) note "SKIPPED: retired VPS must not be modified"; finish ;; esac
  if ! command -v yq >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then step "server group membership (yq and python3 required)" false; finish; fi
  memberships=$(python3 "$DOTFILES_DIR/units/osquery_native_inventory.py" groups "$DOTFILES_DIR/inventory.yml" "$MACHINE" server vps) || { step "host group membership" false; finish; }
  read -r server vps <<< "$memberships"
  case "$server:$vps" in true:true|true:false|false:true) ;; false:false) note "SKIPPED: not a server or VPS"; finish ;; *) step "host group membership" false; finish ;; esac
  if [ "$(id -u)" != 0 ]; then
    if command -v sudo >/dev/null 2>&1 && sudo -n true; then rootcmd=(sudo -n); else step "noninteractive root access" false; finish; fi
  fi

  hardening_line() {
    "${rootcmd[@]}" python3 "$DOTFILES_DIR/units/server-hardening-file.py" "$@"
  }
  local root_options swap_root=unknown
  if root_options=$(findmnt -n -o OPTIONS --mountpoint /); then
    case ",$root_options," in
      *,ro,*) swap_root=readonly ;;
      *,rw,*) swap_root=writable ;;
      *) step "inspect root mount options" false ;;
    esac
  else
    step "inspect root mount options" false
  fi
  hardening_immutable_swap() {
    if swap_output=$("${rootcmd[@]}" swapon --show=NAME --noheadings); then
      if [[ "$swap_output" =~ [^[:space:]] ]]; then
        note "ok    active swap preserved on read-only root"
      else
        step "active swap required on read-only root" false
      fi
    else
      step "inspect active swap on read-only root" false
    fi
  }
  if [ "${UNITS_CHECK:-0}" = 1 ]; then
    local rule pattern line mode chrony_unit chrony_state chrony_active=0
    hardening_inspect_line() {
      local description=$1
      shift
      hardening_line --check "$@"; rc=$?
      case "$rc" in
        0) note "ok    $description" ;;
        10) note "would update $description" ;;
        *) step "inspect $description" false ;;
      esac
    }
    hardening_inspect_line "journald limit (and restart journald)" /etc/systemd/journald.conf '^#?SystemMaxUse=' 'SystemMaxUse=500M'
    if "${rootcmd[@]}" journalctl --disk-usage >/dev/null; then
      note "would vacuum journals to 500M"
    else
      step "inspect journal usage" false
    fi
    if [ "$swap_root" = readonly ]; then
      hardening_immutable_swap
    elif [ "$swap_root" = writable ]; then
      if "${rootcmd[@]}" test -e /swapfile; then
        if mode=$("${rootcmd[@]}" stat -c '%a:%u:%g' /swapfile); then
          [ "$mode" = '600:0:0' ] && note "ok    swap permissions" || note "would set swap ownership and permissions"
        else
          step "inspect swap permissions" false
        fi
      else
        note "would create 2 GiB /swapfile with root ownership and mode 0600"
      fi
      if swap_output=$("${rootcmd[@]}" swapon --show=NAME --noheadings); then
        if printf '%s\n' "$swap_output" | grep -Fxq /swapfile; then
          note "ok    swap enabled"
        else
          note "would format and enable /swapfile"
        fi
      else
        step "inspect active swap" false
      fi
      hardening_inspect_line "swap fstab" /etc/fstab '^/swapfile none swap sw 0 0$' '/swapfile none swap sw 0 0'
    fi
    for chrony_unit in chrony chronyd; do
      chrony_state=$(systemctl show "$chrony_unit" --property=LoadState --property=ActiveState 2>/dev/null); rc=$?
      if [ "$rc" != 0 ] && [[ "$chrony_state" != *'LoadState=not-found'* ]]; then
        step "inspect $chrony_unit" false
      elif [[ "$chrony_state" != *'LoadState='* || "$chrony_state" != *'ActiveState='* ]]; then
        step "inspect $chrony_unit" false
      elif [[ "$chrony_state" != *'LoadState=loaded'* && "$chrony_state" != *'LoadState=not-found'* ]]; then
        step "inspect $chrony_unit" false
      elif [[ "$chrony_state" == *'ActiveState=active'* ]]; then
        chrony_active=1
      fi
    done
    if [ -e /usr/lib/systemd/systemd-timesyncd ] && [ "$chrony_active" = 0 ]; then
      note "would enable and start systemd-timesyncd if chrony is inactive"
    fi
    for rule in 'MaxStartups|MaxStartups 3:50:10' 'MaxSessions|MaxSessions 10' 'ClientAliveCountMax|ClientAliveCountMax 3'; do
      pattern=${rule%%|*}; line=${rule#*|}
      hardening_inspect_line "SSH limit $pattern (and reload SSH)" /etc/ssh/sshd_config "^#?$pattern" "$line"
    done
    if command -v ufw >/dev/null 2>&1; then
      if ufw_output=$("${rootcmd[@]}" ufw status 2>/dev/null); then
        [[ "$ufw_output" != *'Status: active'* ]] || note "would enable UFW logging"
      else
        step "inspect UFW status" false
      fi
    fi
    if command -v pro >/dev/null 2>&1; then
      if pro_output=$("${rootcmd[@]}" pro status --format json 2>/dev/null); then
        if [[ "$pro_output" != *livepatch* ]] || [[ "$pro_output" == *disabled* ]]; then note "would enable livepatch"; fi
      else
        step "inspect Ubuntu Pro status" false
      fi
    fi
    if [ -e /var/run/reboot-required ]; then note "REBOOT REQUIRED on $MACHINE — kernel was updated and needs a restart."; fi
    finish
  fi
  hardening_line /etc/systemd/journald.conf '^#?SystemMaxUse=' 'SystemMaxUse=500M'; rc=$?
  case "$rc" in
    0) note "ok    journald limit" ;;
    10) note "ok    journald limit"; step "restart journald" "${rootcmd[@]}" systemctl restart systemd-journald ;;
    *) step "journald limit" false ;;
  esac
  step "vacuum journals" "${rootcmd[@]}" journalctl --vacuum-size=500M

  if [ "$swap_root" = readonly ]; then
    hardening_immutable_swap
  elif [ "$swap_root" = writable ]; then
    local swap_ready=1
    if [ ! -e /swapfile ]; then
      if ! (umask 077; "${rootcmd[@]}" dd if=/dev/zero of=/swapfile bs=1M count=2048); then
        step "create swap file" false; swap_ready=0
      fi
    fi
    if [ "$swap_ready" = 1 ] && [ -e /swapfile ]; then
      if ! "${rootcmd[@]}" chown root:root /swapfile; then step "protect swap file" false; swap_ready=0; fi
      if ! "${rootcmd[@]}" chmod 0600 /swapfile; then step "set swap permissions" false; swap_ready=0; fi
      if [ "$swap_ready" = 1 ]; then
        if swap_output=$("${rootcmd[@]}" swapon --show=NAME --noheadings); then
          if ! printf '%s\n' "$swap_output" | grep -Fxq /swapfile; then
            if ! "${rootcmd[@]}" mkswap /swapfile; then
              step "format swap" false; swap_ready=0
            elif ! "${rootcmd[@]}" swapon /swapfile; then
              step "enable swap" false; swap_ready=0
            fi
          fi
        else
          step "check active swap" false; swap_ready=0
        fi
      fi
      if [ "$swap_ready" = 1 ]; then
        hardening_line /etc/fstab '^/swapfile none swap sw 0 0$' '/swapfile none swap sw 0 0'; rc=$?
        case "$rc" in 0|10) note "ok    swap fstab" ;; *) step "swap fstab" false ;; esac
      fi
    fi
  fi

  local chrony
  chrony=$(systemctl is-active chrony chronyd 2>/dev/null) || :
  if [ -e /usr/lib/systemd/systemd-timesyncd ] && ! printf '%s\n' "$chrony" | grep -Fxq active; then
    step "enable timesyncd" "${rootcmd[@]}" systemctl enable --now systemd-timesyncd
  fi

  local rule pattern line
  for rule in 'MaxStartups|MaxStartups 3:50:10' 'MaxSessions|MaxSessions 10' 'ClientAliveCountMax|ClientAliveCountMax 3'; do
    pattern=${rule%%|*}; line=${rule#*|}
    hardening_line /etc/ssh/sshd_config "^#?$pattern" "$line"; rc=$?
    case "$rc" in 0) ;; 10) changed=1 ;; *) step "SSH limit $pattern" false ;; esac
  done
  if [ "$changed" = 1 ]; then
    local ssh_unit=sshd
    if [ -r /etc/os-release ]; then
      # shellcheck disable=SC1091
      . /etc/os-release
      case " ${ID:-} ${ID_LIKE:-} " in *' debian '*|*' ubuntu '*) ssh_unit=ssh ;; esac
    fi
    # The role's shared SSH reload handler ignores errors on non-systemd hosts.
    soft "reload SSH" "${rootcmd[@]}" systemctl reload "$ssh_unit"
  fi
  if ufw_output=$(ufw status 2>/dev/null) && [[ "$ufw_output" == *'Status: active'* ]]; then
    step "enable UFW logging" "${rootcmd[@]}" ufw logging on
  fi
  if pro_output=$(pro status --format json 2>/dev/null) && { [[ "$pro_output" != *livepatch* ]] || [[ "$pro_output" == *disabled* ]]; }; then
    soft "enable livepatch" "${rootcmd[@]}" pro enable livepatch
  fi
  if [ -e /var/run/reboot-required ]; then note "REBOOT REQUIRED on $MACHINE — kernel was updated and needs a restart."; fi
  finish
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then hardening_main "$@"; fi
