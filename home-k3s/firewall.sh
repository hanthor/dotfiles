#!/usr/bin/env bash
# Manage cni0 and a source-scoped pod egress policy without reloading firewalld.
# The internal zone's existing services, including SSH, remain reachable
# from pods. Public and Tailscale interface assignments are not changed.
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
policy=k3s-pod-egress
egress_rule='rule family="ipv4" source address="10.42.0.0/16" accept'
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

# Refuse to take over an existing policy whose effects extend beyond this
# script's contract. Partially created policies are safe to finish: their
# target is CONTINUE and each populated field must already be the desired one.
policy_preflight() {
  local scope=$1 policies info line target=0 priority=0 disabled=0
  local -a opts=()
  [ "$scope" = runtime ] || opts=(--permanent)
  policies=$(firewall-cmd "${opts[@]}" --get-policies)
  [[ " $policies " == *" $policy "* ]] || return 0
  info=$(firewall-cmd "${opts[@]}" --info-policy="$policy")
  while IFS= read -r line; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    case "$line" in
      "$policy"|"$policy (active)"|'') ;;
      'disable: no') disabled=1 ;;
      'priority: -1') priority=1 ;;
      'target: CONTINUE') target=1 ;;
      'ingress-zones:'|'ingress-zones: internal'|'egress-zones:'|'egress-zones: public'|\
      'services:'|'ports:'|'protocols:'|'masquerade: no'|'forward-ports:'|\
      'source-ports:'|'icmp-blocks:'|'rich rules:'|"$egress_rule") ;;
      *) echo "$scope: unexpected $policy setting: $line; refusing" >&2; return 1 ;;
    esac
  done <<< "$info"
  if [ "$target" != 1 ] || [ "$priority" != 1 ] || [ "$disabled" != 1 ]; then
    echo "$scope: cannot establish safe $policy defaults; refusing" >&2
    return 1
  fi
}
policy_preflight runtime
policy_preflight permanent

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

check_or_apply_policy() {
  local scope policies
  local -a opts
  for scope in permanent runtime; do
    opts=()
    [ "$scope" = runtime ] || opts=(--permanent)
    policies=$(firewall-cmd "${opts[@]}" --get-policies)
    if [[ " $policies " != *" $policy "* ]]; then
      if [ "$mode" = --check ]; then
        echo "Missing policy $policy ($scope)" >&2
        return 1
      fi
      if [ "$scope" = runtime ]; then
        echo "Permanent $policy staged; runtime policy is absent. Activate only with console recovery; no reload was performed." >&2
        return 1
      fi
      # firewalld can create a policy only in permanent configuration.
      firewall-cmd --permanent --new-policy="$policy"
    fi
    # Install the bounded rule before activating the policy with both zones.
    ensure "--query-rich-rule=$egress_rule" "--add-rich-rule=$egress_rule" "${opts[@]}" --policy="$policy"
    ensure --query-ingress-zone=internal --add-ingress-zone=internal "${opts[@]}" --policy="$policy"
    ensure --query-egress-zone=public --add-egress-zone=public "${opts[@]}" --policy="$policy"
    # Check that successful mutations actually produced the bounded policy,
    # including when the runtime policy has not been loaded yet.
    policy_preflight "$scope"
    local previous_mode=$mode
    mode=--check
    ensure "--query-rich-rule=$egress_rule" "--add-rich-rule=$egress_rule" "${opts[@]}" --policy="$policy"
    ensure --query-ingress-zone=internal --add-ingress-zone=internal "${opts[@]}" --policy="$policy"
    ensure --query-egress-zone=public --add-egress-zone=public "${opts[@]}" --policy="$policy"
    mode=$previous_mode
  done
}
check_or_apply_policy
if [ "$mode" = --apply ]; then
  # Verify the actual runtime and permanent state, not just command success.
  [ "$(firewall-cmd --get-default-zone)" != "$zone" ] || { echo 'internal became the default zone' >&2; exit 1; }
  preflight runtime
  preflight permanent
  policy_preflight runtime
  policy_preflight permanent
  mode=--check
  check_or_apply
  check_or_apply_policy
fi

echo 'internal cni0 forwarding, kubelet rule and pod egress policy are present in runtime and permanent configuration'
