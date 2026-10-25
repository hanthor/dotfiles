#!/usr/bin/env bash
# kube unit: kubeconfig + talosconfig for the home and AWS clusters from Bitwarden notes.
# Seed the home notes with scripts/bw-seed-kube.sh. Desktops only.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=units/kube.conf
. "$DOTFILES_DIR/units/kube.conf"

if ! is_desktop || skipped_by_profile skip_kube; then
  note "SKIPPED: not a desktop (or skip_kube / vm-test)"
  exit 0
fi
s="$(bw_session)"
if [ -z "$s" ]; then
  note "SKIPPED: vault locked or --no-secrets; existing kube/talos configs left untouched"
  exit 0
fi

step "kube dirs" install -d -m 0700 "$HOME/.kube" "$HOME/.talos"

# fetch_note ITEM DEST LABEL: write the note to DEST when Bitwarden has it; prints a warning otherwise.
fetch_note() {
  local item="$1" dest="$2" label="$3" val
  val="$(BW_SESSION="$s" bw get notes "$item" 2>/dev/null)"
  if [ -z "$val" ]; then
    note "warn: $label missing in BW (item $item)"
    return 0
  fi
  printf '%s\n' "$val" | write_atomic "$dest" || return 1
  [ "$dest" != "$HOME/.kube/config" ] || home_written=1
}

# The home kubeconfig is rewritten from Bitwarden each run, so the TLS pin is re-applied each time.
pin_tls() {
  command -v kubectl >/dev/null 2>&1 || { note "warn: kubectl missing; tls-server-name not pinned"; return 0; }
  local c rc=0
  while read -r c; do
    [ -n "$c" ] || continue
    KUBECONFIG="$HOME/.kube/config" kubectl config set-cluster "$c" --tls-server-name="$KUBE_TLS_SERVER_NAME" >/dev/null || rc=1
  done < <(KUBECONFIG="$HOME/.kube/config" kubectl config get-clusters 2>/dev/null | tail -n +2)
  return $rc
}

home_written=0
step "home kubeconfig" fetch_note kubeconfig "$HOME/.kube/config" "kubeconfig (seed with scripts/bw-seed-kube.sh)"
step "home talosconfig" fetch_note talosconfig "$HOME/.talos/config" "talosconfig (seed with scripts/bw-seed-kube.sh)"
[ "$home_written" = 0 ] || step "pin tls-server-name" pin_tls
step "aws kubeconfig" fetch_note kubeconfig-aws-migration "$HOME/.kube/config-aws-migration" "AWS kubeconfig"
step "aws talosconfig" fetch_note talosconfig-aws-migration "$HOME/.talos/config-aws-migration" "AWS talosconfig"
finish
