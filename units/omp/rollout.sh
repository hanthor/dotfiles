#!/usr/bin/env bash
# Reconcile only the shared model config on online, SSH-accessible OMP clients.
set -uo pipefail
root="${DOTFILES_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export DOTFILES_DIR="$root"
ssh_opts=(-o BatchMode=yes -o ConnectTimeout=8 -o ServerAliveInterval=10 -o ServerAliveCountMax=2)
rc=0
for host in $(python3 "$root/scripts/online_hosts.py"); do
  # Raw Android has no OMP build; the phone's supported Debian guest is mumbai.
  [ "$host" != termux ] || continue
  if ! stage=$(ssh "${ssh_opts[@]}" "$host" '
    export PATH="$HOME/.bun/bin:$HOME/.local/bin:/home/linuxbrew/.linuxbrew/bin:/opt/homebrew/bin:$PATH"
    command -v omp >/dev/null && command -v yq >/dev/null || exit 1
    stage=$(mktemp -d /tmp/omp-lemonade.XXXXXXXX) || exit 1
    mkdir -p "$stage/units/omp" || exit 1
    printf "%s\n" "$stage"
  '); then
    echo "Pending: $host (SSH, omp, or yq unavailable)" >&2
    rc=1
    continue
  fi
  if [[ ! "$stage" =~ ^/tmp/omp-lemonade\.[[:alnum:]]+$ ]]; then
    echo "Invalid staging path from $host" >&2
    rc=1
    continue
  fi
  if scp -q "${ssh_opts[@]}" "$root/units/lib.sh" "$host:$stage/units/lib.sh" &&
     scp -q "${ssh_opts[@]}" "$root/units/omp/models.sh" "$root/units/omp/models.yml" "$host:$stage/units/omp/" &&
     ssh "${ssh_opts[@]}" "$host" "export PATH=\"\$HOME/.bun/bin:\$HOME/.local/bin:/home/linuxbrew/.linuxbrew/bin:/opt/homebrew/bin:\$PATH\"; DOTFILES_DIR='$stage' UNITS_NO_SECRETS=1 bash '$stage/units/omp/models.sh'"; then
    echo "Configured: $host"
  else
    echo "Pending: $host (model provisioning failed)" >&2
    rc=1
  fi
  ssh "${ssh_opts[@]}" "$host" "rm -rf -- '$stage'" || rc=1
 done
exit "$rc"
