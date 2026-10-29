#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

osquery_verify_archive() {
  local archive=$1 expected=$2
  shift 2
  printf '%s  %s\n' "$expected" "$archive" | "$@" sha256sum -c --status
}

# Match the role's poller PATH: the user's tools, Homebrew, then the apply PATH.
osquery_default_poll_path() {
  printf '%s' "$HOME/.local/bin:${BREW_PREFIX:-/home/linuxbrew/.linuxbrew}/bin:$PATH"
}

osquery_main() {
  local vps arch version archive checksum supported poller settings skip_setting supported_setting archives override_path override_state pollpath state
  local -a rootcmd=()
  case "$MACHINE" in matrix|telengana) note "SKIPPED: retired VPS"; finish ;; esac
  if [ "$IS_TERMUX" = 1 ] || [ "$IS_MUSL" = 1 ] || [ "$(uname -s)" != Linux ] || [ ! -d /run/systemd/system ]; then
    note "SKIPPED: osquery requires native glibc Linux and systemd"; finish
  fi
  if ! command -v yq >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then step "osquery inventory requires yq and python3" false; finish; fi
  vps=$(python3 "$DOTFILES_DIR/units/osquery_native_inventory.py" groups "$DOTFILES_DIR/inventory.yml" "$MACHINE" vps) || { step "check VPS membership" false; finish; }
  case "$vps" in true) note "SKIPPED: VPS"; finish ;; false) ;; *) step "check VPS membership" false; finish ;; esac
  arch=$(uname -m)
  case "$arch" in x86_64|aarch64) ;; *) note "SKIPPED: unsupported osquery architecture $arch"; finish ;; esac
  local defaults="$DOTFILES_DIR/units/osquery/defaults/main.yml" assets="$DOTFILES_DIR/units/osquery"
  settings=$(python3 "$DOTFILES_DIR/units/osquery_native_inventory.py" osquery-settings "$DOTFILES_DIR/inventory.yml" "$MACHINE") || { step "read osquery host settings" false; finish; }
  osquery_setting() { yq -p=json -r "$1" <<< "$settings"; }
  skip_setting=$(osquery_setting '.skip_osquery') || { step "read osquery skip setting" false; finish; }
  supported_setting=$(osquery_setting '.osquery_supported') || { step "read osquery support setting" false; finish; }
  poller=$(osquery_setting '.osquery_poller_enabled') || { step "read osquery poller setting" false; finish; }
  if [ "$supported_setting" = null ]; then supported_setting=$(yq -r '.osquery_supported' "$defaults") || { step "read osquery support default" false; finish; }; fi
  if [ "$poller" = null ]; then poller=$(yq -r '.osquery_poller_enabled' "$defaults") || { step "read osquery poller default" false; finish; }; fi
  case "$skip_setting:$supported_setting:$poller" in
    true:true:true|true:true:false|true:false:true|true:false:false|null:false:true|null:false:false|false:false:true|false:false:false)
      note "SKIPPED: osquery disabled for this host"; finish ;;
    null:true:true|null:true:false|false:true:true|false:true:false) ;;
    *) step "validate osquery host settings" false; finish ;;
  esac
  version=$(osquery_setting '.osquery_version') || { step "read osquery version override" false; finish; }
  if [ "$version" = null ]; then version=$(yq -r '.osquery_version' "$defaults") || { step "read osquery version" false; finish; }; fi
  archives=$(yq -p=json -o=json -I=0 '.osquery_release_archives' <<< "$settings") || { step "read osquery release override" false; finish; }
  if [ "$archives" = null ]; then archives=$(yq -o=json -I=0 '.osquery_release_archives' "$defaults") || { step "read osquery release defaults" false; finish; }; fi
  archive=$(ARCH="$arch" yq -p=json -r '.[strenv(ARCH)].name' <<< "$archives") || { step "read osquery archive" false; finish; }
  checksum=$(ARCH="$arch" yq -p=json -r '.[strenv(ARCH)].sha256' <<< "$archives") || { step "read osquery checksum" false; finish; }
  override_path=$(osquery_setting '.osquery_poller_path') || { step "read osquery poller path" false; finish; }
  override_state=$(osquery_setting '.osquery_poller_state_dir') || { step "read osquery poller state" false; finish; }
  pollpath=$(osquery_default_poll_path)
  state="$HOME/.local/state/fleet-osquery"
  if [ "$override_path" != null ]; then pollpath=$override_path; fi
  if [ "$override_state" != null ]; then state=$override_state; fi
  if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || [[ ! "$archive" =~ ^osquery-[A-Za-z0-9_.-]+\.tar\.gz$ ]] || [[ ! "$checksum" =~ ^[0-9a-f]{64}$ ]]; then
    step "validate osquery release metadata" false; finish
  fi
  if [ "$(id -u)" != 0 ]; then
    if [ "${UNITS_CHECK:-0}" = 1 ]; then
      if command -v sudo >/dev/null 2>&1; then rootcmd=(sudo -n); else step "noninteractive root access" false; finish; fi
    elif command -v sudo >/dev/null 2>&1 && sudo -n true; then rootcmd=(sudo -n); else step "noninteractive root access" false; finish; fi
  fi
  for supported in systemctl python3; do
    if ! command -v "$supported" >/dev/null 2>&1; then step "osquery dependency $supported" false; finish; fi
  done
  if [ "${UNITS_CHECK:-0}" = 1 ]; then
    if ! command -v sha256sum >/dev/null 2>&1; then step "osquery dependency sha256sum" false; finish; fi
    local user uid gid
    user=$(id -un) && uid=$(id -u) && gid=$(id -g) || { step "read osquery poller identity" false; finish; }
    step "check osquery monitoring and poller" "${rootcmd[@]}" env PYTHONDONTWRITEBYTECODE=1 python3 \
      "$DOTFILES_DIR/units/osquery-check.py" "$DOTFILES_DIR" "$version" "$archive" "$checksum" \
      "$poller" "$pollpath" "$state" "$HOME" "$user" "$uid" "$gid" "$PATH"
    finish
  fi

  local temp
  temp=$(mktemp -d) || { step "create osquery temporary directory" false; finish; }
  trap 'rm -rf -- "$temp"' EXIT
  osquery_install_file() {
    local src=$1 dest=$2 mode=$3
    if "${rootcmd[@]}" cmp -s "$src" "$dest"; then
      "${rootcmd[@]}" chmod "$mode" "$dest" && "${rootcmd[@]}" chown root:root "$dest"
      return
    fi
    "${rootcmd[@]}" install -o root -g root -m "$mode" "$src" "$dest" || return 1
    OSQUERY_CHANGED=1
  }
  osquery_install() {
    local cache="/var/cache/fleet-osquery/$archive" target="/opt/osquery-$version/bin/osqueryd" unit
    local OSQUERY_CHANGED=0 daemon_changed=0
    if ! command -v sha256sum >/dev/null 2>&1; then note "osquery requires sha256sum"; return 1; fi
    "${rootcmd[@]}" install -d -o root -g root -m 0755 /var/cache/fleet-osquery "/opt/osquery-$version" /opt/fleet-osquery || return 1
    if ! osquery_verify_archive "$cache" "$checksum" "${rootcmd[@]}"; then
      if ! command -v curl >/dev/null 2>&1; then note "osquery download requires curl"; return 1; fi
      curl --fail --silent --show-error --location --max-time 120 "https://github.com/osquery/osquery/releases/download/$version/$archive" -o "$temp/$archive" || return 1
      osquery_verify_archive "$temp/$archive" "$checksum" || { note "osquery release checksum mismatch"; return 1; }
      "${rootcmd[@]}" install -o root -g root -m 0644 "$temp/$archive" "$cache" || return 1
    fi
    if [ ! -e "$target" ]; then
      if ! command -v tar >/dev/null 2>&1; then note "osquery extraction requires tar"; return 1; fi
      "${rootcmd[@]}" tar -xzf "$cache" --no-same-owner --strip-components=2 -C "/opt/osquery-$version" opt/osquery/bin/osqueryd || return 1
    fi
    "${rootcmd[@]}" chown root:root "$target" && "${rootcmd[@]}" chmod 0755 "$target" || return 1
    if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then "${rootcmd[@]}" chcon -t bin_t "$target" || return 1; fi
    "${rootcmd[@]}" ln -sfn osqueryd "/opt/osquery-$version/bin/osqueryi" || return 1
    if [ "$(readlink /opt/osquery 2>/dev/null)" != "/opt/osquery-$version" ]; then
      "${rootcmd[@]}" ln -sfnT "/opt/osquery-$version" /opt/osquery || return 1
      daemon_changed=1
    fi
    "${rootcmd[@]}" install -d -o root -g root -m 0700 /etc/osquery /var/lib/osquery /var/log/osquery /var/lib/fleet-osquery || return 1
    osquery_install_file "$assets/files/fleet-osquery.py" /opt/fleet-osquery/fleet-osquery 0755 || return 1
    if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then "${rootcmd[@]}" chcon -t bin_t /opt/fleet-osquery/fleet-osquery || return 1; fi
    # The role's config has no substitutions. Validate before replacing it.
    "${rootcmd[@]}" /opt/osquery/bin/osqueryd --disable_extensions --config_check --config_path="$assets/templates/osquery.conf.j2" || return 1
    OSQUERY_CHANGED=0
    osquery_install_file "$assets/templates/osquery.conf.j2" /etc/osquery/osquery.conf 0600 || return 1
    [ "$OSQUERY_CHANGED" = 0 ] || daemon_changed=1
    OSQUERY_CHANGED=0
    osquery_install_file "$assets/templates/osqueryd.service.j2" /etc/systemd/system/osqueryd.service 0644 || return 1
    [ "$OSQUERY_CHANGED" = 0 ] || daemon_changed=1
    for unit in fleet-osquery-report.service fleet-osquery-report.timer; do
      osquery_install_file "$assets/templates/$unit.j2" "/etc/systemd/system/$unit" 0644 || return 1
    done
    "${rootcmd[@]}" systemctl daemon-reload || return 1
    "${rootcmd[@]}" systemctl enable fleet-osquery-report.timer || return 1
    if [ "$daemon_changed" = 1 ]; then "${rootcmd[@]}" systemctl restart osqueryd.service || return 1; fi
    "${rootcmd[@]}" systemctl enable --now osqueryd.service || return 1
    if [ ! -e /var/lib/fleet-osquery/baseline.json ]; then "${rootcmd[@]}" /opt/fleet-osquery/fleet-osquery baseline --if-missing || return 1; fi
    "${rootcmd[@]}" systemctl start fleet-osquery-report.service || return 1
    "${rootcmd[@]}" systemctl start fleet-osquery-report.timer
  }
  osquery_poller() {
    if [ "$poller" != true ]; then
      if [ -e /etc/systemd/system/fleet-osquery-poll.timer ]; then
        "${rootcmd[@]}" systemctl disable --now fleet-osquery-poll.timer || return 1
        "${rootcmd[@]}" systemctl stop fleet-osquery-poll.service || return 1
      fi
      return 0
    fi
    PATH="$pollpath" python3 "$DOTFILES_DIR/units/osquery-poller-render.py" inventory "$DOTFILES_DIR/inventory.yml" > "$temp/inventory.yml" || return 1
    python3 "$DOTFILES_DIR/units/osquery-poller-render.py" service "$assets/templates/fleet-osquery-poll.service.j2" "$(id -un)" "$(id -g)" "$HOME" "$pollpath" "$state" > "$temp/poll.service" || return 1
    "${rootcmd[@]}" install -d -o root -g root -m 0755 /etc/fleet-osquery /opt/fleet-osquery || return 1
    osquery_install_file "$DOTFILES_DIR/scripts/osquery-fleet.py" /opt/fleet-osquery/osquery-fleet.py 0644 || return 1
    osquery_install_file "$DOTFILES_DIR/scripts/online_hosts.py" /opt/fleet-osquery/online_hosts.py 0644 || return 1
    osquery_install_file "$DOTFILES_DIR/units/osquery_native_inventory.py" /opt/fleet-osquery/osquery_native_inventory.py 0644 || return 1
    osquery_install_file "$temp/inventory.yml" /etc/fleet-osquery/inventory.yml 0644 || return 1
    "${rootcmd[@]}" install -d -o "$(id -u)" -g "$(id -g)" -m 0700 "$state" || return 1
    osquery_install_file "$temp/poll.service" /etc/systemd/system/fleet-osquery-poll.service 0644 || return 1
    unit=fleet-osquery-poll.timer
    osquery_install_file "$assets/templates/$unit.j2" "/etc/systemd/system/$unit" 0644 || return 1
    "${rootcmd[@]}" systemctl daemon-reload || return 1
    "${rootcmd[@]}" systemctl enable --now fleet-osquery-poll.timer || return 1
    "${rootcmd[@]}" systemctl start fleet-osquery-poll.service
  }
  step "osquery monitoring" osquery_install
  step "osquery fleet poller" osquery_poller
  finish
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then osquery_main "$@"; fi
