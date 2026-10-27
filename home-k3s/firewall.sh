#!/usr/bin/env bash
# Explicitly manage only cni0 in firewalld's existing internal zone. The
# internal zone's services, including SSH, remain reachable from pods.
# Neither mode reloads firewalld or changes public/tailscale interfaces.
set -euo pipefail

case "${1:-}" in
  --apply|--check) mode=$1 ;;
  *) echo "Usage: $0 --apply|--check" >&2; exit 2 ;;
esac
[ "$#" -eq 1 ] || { echo "Usage: $0 --apply|--check" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo 'Run as root' >&2; exit 1; }
[ "$(hostname -s)" = karnataka ] || { echo 'Wrong host' >&2; exit 1; }

zone=internal
rule='rule family="ipv4" source address="10.42.0.0/16" destination address="100.66.158.127/32" port port="10250" protocol="tcp" accept'
firewall-cmd --state >/dev/null

# A source binding would classify packets by address even on a public NIC.
# Also refuse unrelated interfaces or a default zone that implicitly includes
# them. Check both stores before making any change.
preflight() {
  local scope=$1 interfaces sources iface
  local -a opts=() names=()
  [ "$scope" = runtime ] || opts=(--permanent)
  interfaces=$(firewall-cmd "${opts[@]}" --zone="$zone" --list-interfaces)
  sources=$(firewall-cmd "${opts[@]}" --zone="$zone" --list-sources)
  [ -z "$sources" ] || { echo "$scope: internal has source bindings; refusing" >&2; return 1; }
  read -r -a names <<< "$interfaces"
  for iface in "${names[@]}"; do
    [ "$iface" = cni0 ] || { echo "$scope: internal contains unrelated interface $iface; refusing" >&2; return 1; }
  done
}
[ "$(firewall-cmd --get-default-zone)" != "$zone" ] || {
  echo 'internal is the default zone; refusing' >&2; exit 1;
}
preflight runtime
preflight permanent

# A false query exits 1; other errors must not be mistaken for missing rules.
ensure() {
  local query=$1 add=$2 rc
  shift 2
  if firewall-cmd --quiet "$@" "$query"; then
    return 0
  else
    rc=$?
    [ "$rc" -eq 1 ] || return "$rc"
  fi
  if [ "$mode" = --check ]; then
    echo "Missing $query ($*)" >&2
    return 1
  fi
  firewall-cmd "$@" "$add"
}

check_or_apply() {
  local scope
  local -a opts
  for scope in permanent runtime; do
    opts=()
    [ "$scope" = runtime ] || opts=(--permanent)
    # Install the bounded rule and intra-zone forwarding before binding cni0.
    ensure "--query-rich-rule=$rule" "--add-rich-rule=$rule" "${opts[@]}" --zone="$zone"
    ensure --query-forward --add-forward "${opts[@]}" --zone="$zone"
    ensure --query-interface=cni0 --change-interface=cni0 "${opts[@]}" --zone="$zone"
  done
}
check_or_apply
if [ "$mode" = --apply ]; then
  # Verify the actual runtime and permanent state, not just command success.
  [ "$(firewall-cmd --get-default-zone)" != "$zone" ] || { echo 'internal became the default zone' >&2; exit 1; }
  preflight runtime
  preflight permanent
  mode=--check
  check_or_apply
fi

echo 'internal cni0 forwarding and kubelet rule are present in runtime and permanent configuration'
