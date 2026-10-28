#!/usr/bin/env bash
# Propose an inventory-only registration without modifying the caller's checkout.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
name=${1:?machine name required}
type=${2:-desktop}
case "$name" in matrix|telengana) echo "Retired VPSes must not be modified." >&2; exit 2 ;; esac
# Validate before using the name in paths, branch names or commands.
python3 - "$repo/scripts" "$name" "$type" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from inventory_parser import validate_host_name
try:
    validate_host_name(sys.argv[2])
    if sys.argv[3] not in ('desktop', 'server', 'vps', 'termux_hosts'):
        raise ValueError('machine type must be desktop, server, vps, or termux_hosts')
except ValueError as error:
    print(error, file=sys.stderr)
    sys.exit(2)
PY

git -C "$repo" fetch origin '+refs/heads/master:refs/remotes/origin/master'
base=$(git -C "$repo" rev-parse refs/remotes/origin/master)
tmp=$(mktemp -d)
worktree="$tmp/worktree"
cleanup() {
  if [ -e "$worktree/.git" ]; then git -C "$repo" worktree remove --force "$worktree" || true; fi
  rm -rf -- "$tmp"
}
trap cleanup EXIT
git -C "$repo" worktree add --detach "$worktree" "$base"
rc=0
python3 "$repo/scripts/register-machine.py" --check "$name" "$type" "$worktree/inventory.yml" || rc=$?
case "$rc" in
  0) echo "$name is already registered as $type on origin/master."; exit 0 ;;
  3) ;;
  *) exit "$rc" ;;
esac
if [ "$type" = termux_hosts ]; then
  echo "New Termux identities need an individually reviewed inventory PR with the correct Android Tailscale name, SSH user and port; add the host to termux_hosts, merge, then rerun." >&2
  exit 1
fi
command -v gh >/dev/null 2>&1 || { echo "GitHub CLI (gh) is required to propose registration; use an authenticated fleet checkout." >&2; exit 1; }
branch="onboarding/$name"
pr=$(cd "$worktree" && gh pr list --base master --head "$branch" --state open --json url --jq '.[0].url // empty')
if [ -n "$pr" ]; then
  echo "Registration awaits review and merge: $pr"
  exit 3
fi
rc=0
git -C "$repo" ls-remote --exit-code origin "refs/heads/$branch" >/dev/null || rc=$?
if [ "$rc" -eq 0 ]; then
  echo "Remote branch $branch already exists without an open PR; inspect it rather than overwriting it." >&2
  exit 1
elif [ "$rc" -ne 2 ]; then
  echo "Could not inspect remote registration branch." >&2
  exit "$rc"
fi
python3 "$repo/scripts/register-machine.py" "$name" "$type" "$worktree/inventory.yml"
mkdir -p "$worktree/host_vars"
if [ ! -e "$worktree/host_vars/$name.yml" ]; then printf '%s\n' '---' > "$worktree/host_vars/$name.yml"; fi
git -C "$worktree" add -- inventory.yml "host_vars/$name.yml"
git -C "$worktree" commit -m "inventory: add $name ($type)"
# The empty lease requires the remote branch not to exist; never replace anyone's branch.
git -C "$worktree" push --force-with-lease="refs/heads/$branch:" origin "HEAD:refs/heads/$branch"
if ! (cd "$worktree" && gh pr create --base master --head "$branch" --title "inventory: add $name ($type)" --body "Register $name as a $type. Review the inventory and host-specific settings before merging." ); then
  echo "PR creation failed; branch $branch was retained. Inspect it and create the PR with gh pr create --base master --head $branch." >&2
  exit 1
fi
echo "Review and merge the registration PR, then rerun the onboarding command."
exit 3
