#!/usr/bin/env bash
# Opt-in, temporary runtime bridge. Never reloads firewalld or edits permanent state.
set -Eeuo pipefail

case "${1:-}" in
  --apply|--status|--commit|--cleanup|--timer-rollback) mode=$1 ;;
  *) echo "Usage: $0 --apply|--status|--commit|--cleanup" >&2; exit 2 ;;
esac
[ "$#" -eq 1 ] || { echo "Usage: $0 --apply|--status|--commit|--cleanup" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo 'Run as root' >&2; exit 1; }
[ "$(hostname -s)" = karnataka ] || { echo 'Wrong host' >&2; exit 1; }

policy=gateway-lan-to-world
timer=k3s-egress-bridge-rollback.timer
unit=k3s-egress-bridge-rollback
state=${K3S_BRIDGE_STATE_DIR:-/run/k3s-egress-bridge}
rule4='rule priority="-1" family="ipv4" source NOT address="10.42.0.0/16" drop'
rule6='rule priority="-1" family="ipv6" source address="::/0" drop'
fw() { timeout 20 firewall-cmd "$@"; }

# Compare lists as sets without accepting duplicates or additional entries.
same_words() {
  local actual=$1 expected=$2 word
  local -a got=() want=()
  read -r -a got <<< "$actual"
  read -r -a want <<< "$expected"
  [ "${#got[@]}" = "${#want[@]}" ] || return 1
  for word in "${want[@]}"; do
    [[ " $actual " == *" $word "* ]] || return 1
  done
}

zone_preflight() {
  local scope zone zones interfaces sources
  local -a opts=()
  [ "$(fw --get-default-zone)" != internal ] || { echo 'internal is the default zone; refusing' >&2; return 1; }
  for scope in runtime permanent; do
    opts=(); [ "$scope" = runtime ] || opts=(--permanent)
    interfaces=$(fw "${opts[@]}" --zone=internal --list-interfaces)
    [ "$interfaces" = cni0 ] || { echo "$scope: internal must contain only cni0; refusing" >&2; return 1; }
    zones=$(fw "${opts[@]}" --get-zones)
    [ -n "$zones" ] || { echo "$scope: no zones returned; refusing" >&2; return 1; }
    for zone in $zones; do
      sources=$(fw "${opts[@]}" --zone="$zone" --list-sources)
      [ -z "$sources" ] || { echo "$scope: $zone has source bindings; refusing" >&2; return 1; }
    done
  done
}

# Inspect all printed fields, not just the two rules. Unknown or additional
# settings are drift and must not be enabled or committed by this helper.
policy_state() {
  local expected=$1 info line ingress='' egress='' services=''
  local target=0 priority=0 disabled=0 seen4=0 seen6=0
  info=$(fw --info-policy="$policy")
  while IFS= read -r line; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    case "$line" in
      "$policy"|"$policy (active)"|"$policy (disabled)"|'') ;;
      'target: ACCEPT') target=1 ;;
      'priority: 1000') priority=1 ;;
      'disable: yes') [ "$expected" != active ] || return 1; disabled=1 ;;
      'disable: no') [ "$expected" = active ] || return 1; disabled=1 ;;
      'ingress-zones:'*) ingress=${line#ingress-zones:}; ingress=${ingress# } ;;
      'egress-zones:'*) egress=${line#egress-zones:}; egress=${egress# } ;;
      'services:'*) services=${line#services:}; services=${services# } ;;
      'ports:'|'protocols:'|'masquerade: no'|'forward-ports:'|'source-ports:'|'icmp-blocks:'|'rich rules:') ;;
      "$rule4") seen4=$((seen4 + 1)) ;;
      "$rule6") seen6=$((seen6 + 1)) ;;
      *) echo "Unexpected $policy setting: $line" >&2; return 1 ;;
    esac
  done <<< "$info"
  [ "$target" = 1 ] && [ "$priority" = 1 ] && [ "$disabled" = 1 ] && same_words "$services" 'ftp tftp' || return 1
  if [ "$expected" = baseline ]; then
    same_words "$ingress" 'internal home trusted' && same_words "$egress" 'external public' && [ "$seen4" = 0 ] && [ "$seen6" = 0 ]
  else
    same_words "$ingress" internal && same_words "$egress" public && [ "$seen4" = 1 ] && [ "$seen6" = 1 ]
  fi || { echo "$policy does not match expected $expected state" >&2; return 1; }
}

# Query false is status 1; never mistake an actual error for false.
ensure_present() {
  local query=$1 add=$2 rc
  if fw --quiet --policy="$policy" "$query"; then return 0; else rc=$?; fi
  [ "$rc" = 1 ] || return "$rc"
  fw --policy="$policy" "$add"
}
ensure_absent() {
  local query=$1 remove=$2 rc
  if fw --quiet --policy="$policy" "$query"; then
    fw --policy="$policy" "$remove"
  else
    rc=$?; [ "$rc" = 1 ] || return "$rc"
  fi
}
rollback() {
  # Disable first, before widening zones or removing either protective rule.
  ensure_present --query-disable --add-disable || return 1
  ensure_absent "--query-rich-rule=$rule4" "--remove-rich-rule=$rule4" || return 1
  ensure_absent "--query-rich-rule=$rule6" "--remove-rich-rule=$rule6" || return 1
  ensure_present --query-ingress-zone=home --add-ingress-zone=home || return 1
  ensure_present --query-ingress-zone=trusted --add-ingress-zone=trusted || return 1
  ensure_present --query-egress-zone=external --add-egress-zone=external || return 1
  policy_state baseline || { echo 'Rollback incomplete; policy is disabled, inspect it from the console' >&2; return 1; }
}

fw --state >/dev/null
if [ "$mode" = --status ]; then
  if [ -d "$state" ]; then
    if systemctl is-active --quiet "$timer"; then echo 'Rollback timer: armed'; else echo 'Rollback timer: not armed'; fi
    [ ! -e "$state/committed" ] || echo 'Bridge: committed until firewalld restarts or cleanup'
  else
    echo 'Bridge: no managed runtime state'
  fi
  fw --info-policy="$policy"
  exit 0
fi

if [ "$mode" = --apply ]; then
  zone_preflight
  policy_state baseline || { echo 'Gateway baseline differs; refusing' >&2; exit 1; }
  systemctl is-active --quiet "$timer" && { echo 'Rollback timer already active; refusing' >&2; exit 1; }
  systemctl is-active --quiet "$unit.service" && { echo 'Rollback service still running; refusing' >&2; exit 1; }
  mkdir -m 0700 -- "$state" || { echo 'Bridge state already exists; inspect --status and use --cleanup' >&2; exit 1; }
  # The timer runs a private root-owned snapshot, not a mutable checkout.
  if ! install -m 0700 -- "$(readlink -f -- "$0")" "$state/helper"; then
    rmdir -- "$state"
    echo 'Could not prepare rollback snapshot; no firewall changes made' >&2; exit 1
  fi
else
  [ -f "$state/helper" ] || { echo 'No managed bridge state; refusing' >&2; exit 1; }
fi
exec 9>"$state/lock"
flock -w 300 9 || { echo 'Could not acquire bridge lock' >&2; exit 1; }

case "$mode" in
  --apply)
    # Arm and verify the timer before any runtime firewall mutation.
    if ! systemd-run --unit="$unit" --on-active=15m --setenv="K3S_BRIDGE_STATE_DIR=$state" \
      /bin/bash "$state/helper" --timer-rollback; then
      echo 'Could not schedule rollback; no firewall changes made' >&2; exit 1
    fi
    if ! systemctl is-active --quiet "$timer"; then
      echo 'Rollback timer not active; no firewall changes made' >&2; exit 1
    fi
    # Do not let the timer touch unrelated drift if no mutation was attempted.
    zone_preflight
    policy_state baseline
    : > "$state/dirty"
    on_error() {
      local rc=$?
      trap - ERR
      echo 'Bridge apply failed; restoring disabled gateway baseline' >&2
      if rollback; then
        rm -f -- "$state/dirty"
      else
        echo 'Rollback failed; timer remains armed; use console recovery' >&2
      fi
      exit "$rc"
    }
    trap on_error ERR
    fw --policy="$policy" "--add-rich-rule=$rule4"
    fw --policy="$policy" "--add-rich-rule=$rule6"
    fw --policy="$policy" --remove-ingress-zone=home
    fw --policy="$policy" --remove-ingress-zone=trusted
    fw --policy="$policy" --remove-egress-zone=external
    policy_state prepared
    zone_preflight
    fw --policy="$policy" --remove-disable
    policy_state active
    zone_preflight
    trap - ERR
    echo 'Bridge active; rollback timer is armed. Verify a new SSH session and pod egress before --commit.'
    ;;
  --commit)
    [ -e "$state/dirty" ] || { echo 'No active managed bridge; refusing commit' >&2; exit 1; }
    systemctl is-active --quiet "$timer" || { echo 'Rollback timer is not armed; refusing commit' >&2; exit 1; }
    zone_preflight
    policy_state active || { echo 'Bridge drifted; refusing commit' >&2; exit 1; }
    # If the timer already launched, its locked callback sees this marker.
    : > "$state/committed"
    if ! systemctl stop "$timer"; then
      rm -f -- "$state/committed"
      echo 'Could not stop rollback timer; bridge remains uncommitted' >&2; exit 1
    fi
    echo 'Bridge committed until firewalld restarts; use --cleanup to restore the baseline.'
    ;;
  --cleanup)
    if [ -e "$state/dirty" ]; then rollback; else policy_state baseline; fi
    if systemctl is-active --quiet "$timer"; then systemctl stop "$timer"; fi
    rm -f -- "$state/dirty" "$state/committed" "$state/helper" "$state/lock"
    rmdir -- "$state"
    echo 'Gateway baseline restored; rollback timer stopped.'
    ;;
  --timer-rollback)
    [ ! -e "$state/committed" ] || exit 0
    [ -e "$state/dirty" ] || exit 0
    rollback
    rm -f -- "$state/dirty"
    echo 'Rollback timer restored the gateway baseline.'
    ;;
esac
