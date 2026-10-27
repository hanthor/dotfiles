#!/usr/bin/env bash
# Run the fleet units in prerequisite order, continuing after independent failures.
# Usage: scripts/run-units.sh [--no-secrets] [--tags a,b]
set -uo pipefail

ALL_UNITS="sudo sshd apk-packages termux-packages homebrew flatpak chezmoi fonts omp atuin shell-ai ssh-keys ssh-mesh github kube forgejo-registry tailscale bluefin gnome zen-browser browser-fxa pipewire-audio syncthing hive-ops laptop-services system-services osquery server-hardening retired-services proxy tailscale-cert bst-dashboard kirocrew fleet-facts"
tasks_for_tag() { case "$1" in
  system) echo "sudo sshd apk-packages termux-packages retired-services server-hardening" ;;
  sudo) echo sudo ;;
  sshd) echo sshd ;;
  packages) echo "apk-packages termux-packages homebrew flatpak" ;;
  apk) echo apk-packages ;;
  termux) echo termux-packages ;;
  homebrew) echo homebrew ;;
  flatpak) echo flatpak ;;
  dotfiles) echo "chezmoi fonts omp atuin shell-ai" ;;
  shell) echo "chezmoi fonts atuin shell-ai" ;;
  fonts) echo fonts ;;
  git|neovim|editor) echo chezmoi ;;
  atuin) echo atuin ;;
  ai) echo shell-ai ;;
  secrets) echo "atuin shell-ai ssh-keys github kube forgejo-registry tailscale browser-fxa" ;;
  ssh|ssh_keys) echo "ssh-keys ssh-mesh" ;;
  mesh_check) echo ssh-mesh ;;
  github) echo github ;;
  kube) echo kube ;;
  forgejo|registry) echo forgejo-registry ;;
  tailscale) echo tailscale ;;
  omp) echo omp ;;
  desktop) echo "flatpak bluefin gnome zen-browser browser-fxa pipewire-audio" ;;
  bluefin) echo bluefin ;;
  gnome) echo gnome ;;
  browser|zen_browser) echo "zen-browser browser-fxa" ;;
  audio|pipewire) echo pipewire-audio ;;
  services) echo "syncthing laptop-services system-services osquery proxy tailscale-cert bst-dashboard kirocrew" ;;
  syncthing) echo syncthing ;;
  systemd) echo "laptop-services system-services" ;;
  osquery) echo osquery ;;
  security) echo "osquery server-hardening" ;;
  hardening) echo server-hardening ;;
  retired_services) echo retired-services ;;
  proxy|caddy) echo proxy ;;
  tailscale_cert) echo tailscale-cert ;;
  bst_dashboard) echo bst-dashboard ;;
  kirocrew) echo kirocrew ;;
  hive|hive_ops) echo hive-ops ;;
  facts|fleet_facts) echo fleet-facts ;;
esac; }

repo="$(cd "$(dirname "$0")/.." && pwd)"
export DOTFILES_DIR="$repo"
PATH="$PATH:/home/linuxbrew/.linuxbrew/bin"

tags=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-secrets) export UNITS_NO_SECRETS=1 ;;
    --tags)
      [ $# -ge 2 ] && [ -n "$2" ] || { echo 'missing value for --tags' >&2; exit 2; }
      case "$2" in ,*|*,|*,,*) echo 'empty unit tag' >&2; exit 2 ;; esac
      tags="$2"; shift ;;
    *) echo "usage: $0 [--no-secrets] [--tags a,b]" >&2; exit 2 ;;
  esac
  shift
done

wanted=" "
if [ -z "$tags" ]; then
  wanted=" $ALL_UNITS "
else
  IFS=',' read -ra tag_list <<< "$tags"
  for t in "${tag_list[@]}"; do
    mapped=$(tasks_for_tag "$t")
    if [ -z "$mapped" ]; then echo "unknown unit tag: $t" >&2; exit 2; fi
    read -ra mapped_units <<< "$mapped"
    for u in "${mapped_units[@]}"; do wanted="$wanted$u "; done
  done
fi
selected() { case "$wanted" in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

cd "$repo" || exit 1
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  # mise trust updates user configuration; do not write it during a check.
  have_mise=0
elif command -v mise >/dev/null 2>&1; then
  mise trust -q "$repo/mise.toml" >/dev/null 2>&1 || true
  have_mise=1
else
  echo "mise not installed; running units sequentially"
  have_mise=0
fi

# A stage runs selected units in parallel where available. Non-selected
# prerequisites are never implicitly applied by a tag-only invocation.
run_stage() {
  local unit rc=0
  local -a units=() args=()
  for unit in "$@"; do selected "$unit" && units+=("$unit"); done
  [ "${#units[@]}" -gt 0 ] || return 0
  if [ "$have_mise" = 1 ]; then
    for unit in "${units[@]}"; do
      [ "${#args[@]}" -eq 0 ] || args+=(":::")
      args+=("unit:$unit")
    done
    mise run --continue-on-error --jobs "${UNITS_JOBS:-8}" --output prefix --timeout 15m "${args[@]}"
  else
    for unit in "${units[@]}"; do bash "$repo/units/$unit.sh" || rc=1; done
    return "$rc"
  fi
}

rc=0
# Package managers and the audio unit must not transact concurrently. Packages
# also provide yq/chezmoi on new machines, before inventory-dependent units.
for unit in sudo apk-packages termux-packages homebrew flatpak sshd; do
  run_stage "$unit" || rc=1
done
ssh_ok=1; run_stage ssh-keys || { ssh_ok=0; rc=1; }
tailscale_ok=1; run_stage tailscale || { tailscale_ok=0; rc=1; }
# Desktop settings and profile creation are ordered to avoid overwriting one
# another; other independent units can still run when one step fails.
for unit in chezmoi bluefin gnome; do
  run_stage "$unit" || rc=1
done
zen_ok=1; run_stage zen-browser || { zen_ok=0; rc=1; }

later=(fonts omp atuin shell-ai kube forgejo-registry pipewire-audio syncthing hive-ops laptop-services system-services osquery server-hardening retired-services bst-dashboard kirocrew)
if [ "$zen_ok" = 1 ]; then
  later+=(browser-fxa)
elif selected browser-fxa; then
  echo "SKIPPED: browser-fxa requires a configured Zen profile" >&2
fi
if [ "$ssh_ok" = 1 ]; then
  later+=(ssh-mesh github)
else
  for unit in ssh-mesh github; do selected "$unit" && echo "SKIPPED: $unit requires a valid SSH identity" >&2; done
fi
if [ "$tailscale_ok" = 1 ]; then
  later+=(proxy tailscale-cert)
else
  for unit in proxy tailscale-cert; do selected "$unit" && echo "SKIPPED: $unit requires Tailscale" >&2; done
fi
run_stage "${later[@]}" || rc=1
run_stage fleet-facts || rc=1
exit "$rc"
