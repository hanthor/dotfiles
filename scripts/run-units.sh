#!/usr/bin/env bash
# Run the bash units (units/*.sh) through mise, in parallel, failure-isolated.
# Usage: scripts/run-units.sh [--no-secrets] [--tags a,b]
set -uo pipefail

ALL_UNITS="chezmoi fonts omp atuin shell-ai github kube forgejo-registry"  # run order for the sequential fallback; keep in step with mise.toml
tasks_for_tag() { case "$1" in        # Ansible tag -> units (mirrors the old role tags)
  dotfiles)           echo "chezmoi fonts omp atuin shell-ai" ;;
  shell)              echo "chezmoi fonts atuin shell-ai" ;;
  fonts)              echo fonts ;;
  git|neovim|editor)  echo chezmoi ;;
  atuin)              echo atuin ;;
  ai)                 echo shell-ai ;;
  secrets)            echo "atuin shell-ai github kube forgejo-registry" ;;
  github)             echo github ;;
  kube)               echo kube ;;
  forgejo|registry)   echo forgejo-registry ;;
  omp)                echo omp ;;
esac; }

repo="$(cd "$(dirname "$0")/.." && pwd)"
export DOTFILES_DIR="$repo"
PATH="$PATH:/home/linuxbrew/.linuxbrew/bin"

tags=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-secrets) export UNITS_NO_SECRETS=1 ;;
    --tags) tags="${2:-}"; shift ;;
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
    for u in $(tasks_for_tag "$t"); do wanted="$wanted$u "; done
  done
fi
selected=()
for u in $ALL_UNITS; do
  case "$wanted" in *" $u "*) selected+=("$u") ;; esac
done
[ "${#selected[@]}" -gt 0 ] || exit 0

cd "$repo" || exit 1
if command -v mise >/dev/null 2>&1; then
  mise trust -q "$repo/mise.toml" >/dev/null 2>&1 || true
  args=()
  for u in "${selected[@]}"; do
    [ "${#args[@]}" -gt 0 ] && args+=(":::")
    args+=("unit:$u")
  done
  exec mise run --continue-on-error --jobs "${UNITS_JOBS:-8}" --output prefix --timeout 15m "${args[@]}"
fi

echo "mise not installed; running units sequentially (brew install mise for parallel runs)"
rc=0
for u in "${selected[@]}"; do
  bash "$repo/units/$u.sh" || rc=1
done
exit $rc
