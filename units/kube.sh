#!/usr/bin/env bash
# K3s is the fleet default; historical Talos configs remain recovery material.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=units/kube.conf
. "$DOTFILES_DIR/units/kube.conf"

if skipped_by_profile skip_kube; then
  note "SKIPPED: skip_kube / vm-test"
  exit 0
fi
case "$(uname -s)" in
  Linux|Darwin) ;;
  *) note "SKIPPED: unsupported kubectl platform"; exit 0 ;;
esac

if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if [ "${UNITS_NO_SECRETS:-0}" = 1 ]; then
    note "SKIPPED: secrets disabled; existing kube/talos configs left untouched"
    exit 0
  fi
  for dir in "$HOME/.kube" "$HOME/.talos"; do
    if [ ! -e "$dir" ]; then
      note "PARTIAL: $dir absent; apply would create it if the vault is unlocked"
    elif [ ! -d "$dir" ] || ! mode="$(stat -Lc '%a' "$dir" 2>/dev/null || stat -Lf '%Lp' "$dir" 2>/dev/null)"; then
      note "FAIL  cannot inspect directory $dir"
    elif [ "$mode" != 700 ]; then
      note "PARTIAL: $dir mode differs from 0700; apply would change it if the vault is unlocked"
    else
      note "ok    $dir mode 0700"
    fi
  done
  for path in "$HOME/.kube/config" "$HOME/.kube/config-karnataka-k3s" "$HOME/.kube/config-home-talos" "$HOME/.talos/config" "$HOME/.kube/config-aws-migration" "$HOME/.talos/config-aws-migration"; do
    if [ -L "$path" ] || [ ! -e "$path" ]; then
      note "PARTIAL: $path absent or symlinked; apply requires a regular config file"
    elif [ ! -f "$path" ] || ! mode="$(stat -c '%a' "$path" 2>/dev/null || stat -f '%Lp' "$path" 2>/dev/null)"; then
      note "FAIL  cannot inspect $path"
    elif [ "$mode" != 600 ]; then
      note "PARTIAL: $path mode differs from 0600"
    else
      note "ok    $path mode 0600"
    fi
  done
  note "FAIL  cannot compare kube/talos notes or default context safely: Bitwarden item reads may persist audit events"
  exit 1
fi
s=""
if [ "${KUBE_CACHED_ONLY:-0}" != 1 ]; then
  s="$(bw_session)"
  if [ -z "$s" ]; then
    note "SKIPPED: vault locked or --no-secrets; existing kube/talos configs left untouched"
    exit 0
  fi
fi
if ! command -v kubectl >/dev/null 2>&1; then
  note "FAIL  kubectl missing; apply packages before kube"
  exit 1
fi
step "kube dir" install -d -m 0700 "$HOME/.kube"
if [ "${KUBE_CACHED_ONLY:-0}" != 1 ]; then
  step "talos dir" install -d -m 0700 "$HOME/.talos"
fi
[ "$UNIT_FAILED" = 0 ] || finish
work="$(umask 077; mktemp -d "$HOME/.kube/.fleet.XXXXXX")" || exit 1
trap 'rm -rf "$work"' EXIT

# Never replace a symlink, special file, or an existing recovery cache.
regular_or_absent() {
  if [ -L "$1" ] || { [ -e "$1" ] && [ ! -f "$1" ]; }; then
    note "FAIL  refusing non-regular config $1"
    return 1
  fi
}
fetch_note() {
  local item="$1" dest="$2" val
  if ! val="$(BW_SESSION="$s" bw get notes "$item" 2>/dev/null)" || [ -z "$val" ]; then
    note "warn: $item missing in BW; existing config left untouched"
    return 2
  fi
  printf '%s\n' "$val" | write_atomic "$dest"
}
seed_recovery() {
  local item="$1" dest="$2"
  regular_or_absent "$dest" || return 1
  if [ -f "$dest" ]; then chmod 600 "$dest"; return; fi
  # Historical notes are optional; write failures still fail the unit.
  local rc=0
  fetch_note "$item" "$dest" || rc=$?
  [ "$rc" = 0 ] || [ "$rc" = 2 ]
}
pin_home_recovery() {
  local c clusters header=1
  if ! clusters="$(KUBECONFIG="$work/home" kubectl config get-clusters 2>/dev/null)"; then
    note "FAIL  cannot list home kubeconfig clusters; recovery cache not installed"
    return 1
  fi
  while IFS= read -r c; do
    if [ "$header" = 1 ]; then header=0; continue; fi
    [ -n "$c" ] || continue
    KUBECONFIG="$work/home" kubectl config set-cluster "$c" --tls-server-name="$KUBE_TLS_SERVER_NAME" >/dev/null 2>&1 || return 1
  done <<< "$clusters"
}
seed_home() {
  regular_or_absent "$HOME/.kube/config-home-talos" || return 1
  if [ -f "$HOME/.kube/config-home-talos" ]; then chmod 600 "$HOME/.kube/config-home-talos"; return; fi
  local rc=0
  fetch_note kubeconfig "$work/home" || rc=$?
  [ "$rc" != 2 ] || return 0
  [ "$rc" = 0 ] || return 1
  pin_home_recovery && write_atomic "$HOME/.kube/config-home-talos" < "$work/home"
}
configure_k3s() {
  local dest="$HOME/.kube/config" cache="$HOME/.kube/config-karnataka-k3s" inputs backup="$HOME/.kube/config-pre-karnataka-k3s"
  regular_or_absent "$dest" && regular_or_absent "$cache" && regular_or_absent "$backup" || return 1
  # A failed refresh may use the last successful K3s cache, never partial stdout.
  if [ "${KUBE_CACHED_ONLY:-0}" = 1 ] || ! fetch_note kubeconfig-karnataka-k3s "$work/k3s"; then
    if [ ! -s "$cache" ]; then
      note "FAIL  Karnataka K3s note unavailable and no cached config exists"
      return 1
    fi
    cat "$cache" > "$work/k3s" || return 1
  fi
  # Validate and select the reserved context before touching any deployed config.
  if ! KUBECONFIG="$work/k3s" kubectl config use-context karnataka-k3s >/dev/null 2>&1; then
    note "FAIL  Karnataka K3s config lacks a usable karnataka-k3s context"
    return 1
  fi
  inputs="$work/k3s"
  # Existing contexts take precedence over recovery notes; only K3s is managed.
  [ ! -s "$dest" ] || inputs="$inputs:$dest"
  [ ! -s "$HOME/.kube/config-home-talos" ] || inputs="$inputs:$HOME/.kube/config-home-talos"
  if ! KUBECONFIG="$inputs" kubectl config view --merge --flatten --raw > "$work/merged" 2>/dev/null || [ ! -s "$work/merged" ]; then
    note "FAIL  cannot merge kubeconfigs; existing default left untouched"
    return 1
  fi
  if ! KUBECONFIG="$work/merged" kubectl config use-context karnataka-k3s >/dev/null 2>&1; then
    note "FAIL  cannot select Karnataka K3s; existing default left untouched"
    return 1
  fi
  if [ -f "$dest" ] && [ ! -e "$backup" ] &&
     [ -z "$(KUBECONFIG="$dest" kubectl config get-contexts karnataka-k3s -o name 2>/dev/null)" ]; then
    write_atomic "$backup" < "$dest" || return 1
  fi
  write_atomic "$cache" < "$work/k3s" && write_atomic "$dest" < "$work/merged"
}

if [ "${KUBE_CACHED_ONLY:-0}" != 1 ]; then
  step "home recovery kubeconfig" seed_home
  step "home talosconfig" seed_recovery talosconfig "$HOME/.talos/config"
  step "aws kubeconfig" seed_recovery kubeconfig-aws-migration "$HOME/.kube/config-aws-migration"
  step "aws talosconfig" seed_recovery talosconfig-aws-migration "$HOME/.talos/config-aws-migration"
fi
step "Karnataka K3s default" configure_k3s
finish
