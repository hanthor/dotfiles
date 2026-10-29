#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=units/platform-config.bash
. "$DOTFILES_DIR/units/platform-config.bash"
host_file="$DOTFILES_DIR/host_vars/$MACHINE.yml"
if { [ -e "$host_file" ] || [ -L "$host_file" ]; } && { [ ! -f "$host_file" ] || [ ! -r "$host_file" ]; }; then
  step 'read sudo host configuration' false
  finish
fi

if [ "$(host_var skip_sudo false)" = true ]; then
  note 'SKIPPED: sudo disabled for this host'
  finish
fi
user="$(id -un)" || { step 'determine sudo user' false; finish; }
case "$user" in ''|*[!a-zA-Z0-9_.-]*) step 'invalid sudo user name' false; finish ;; esac
root="${DOTFILES_SYSTEM_ROOT:-}"
dir="$root/etc/sudoers.d"
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  # A non-interactive privileged read is needed for root-owned 0440 sudoers.
  # Keep the entire inspection in one invocation so sudo failure cannot be
  # mistaken for a missing file or a content mismatch.
  check_sudo_policy() {
    platform_root bash -s -- "$dir" "$user" <<'CHECK'
dir=$1 user=$2
if [ ! -d "$dir" ] || [ ! -r "$dir" ] || [ ! -x "$dir" ]; then
  echo "Cannot inspect sudoers directory: $dir" >&2
  exit 1
fi
dest="$dir/zz-$user"
changed=0
if [ -L "$dest" ] || [ ! -e "$dest" ]; then
  changed=1
elif [ ! -f "$dest" ]; then
  echo "Cannot replace non-file sudo policy: $dest" >&2
  exit 1
else
  state=$(stat -c '%a:%u:%g' "$dest") || exit 1
  if printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$user" | cmp -s - "$dest"; then
    :
  else
    rc=$?
    if [ "$rc" -ne 1 ]; then echo "Cannot read sudo policy: $dest" >&2; exit 1; fi
    changed=1
  fi
  [ "$state" = '440:0:0' ] || changed=1
fi
echo 'would validate sudo policy with visudo'
if [ "$changed" = 1 ]; then echo "would install sudo policy: $dest"; else echo "ok    sudo policy: $dest"; fi
for old in "$dir/$user" "$dir/99-$user"; do
  if [ -e "$old" ] || [ -L "$old" ]; then
    if [ -d "$old" ] && [ ! -L "$old" ]; then
      echo "Cannot remove sudo policy directory: $old" >&2
      exit 1
    fi
    echo "would remove legacy sudo policy: $old"
  fi
done
CHECK
  }
  step 'inspect sudo policy' check_sudo_policy
  finish
fi
tmp="$(mktemp -d)" || { step 'create sudo staging directory' false; finish; }
trap 'rm -rf "$tmp"' EXIT

install_sudo_policy() {
  local candidate="$tmp/sudoers" dest="$dir/zz-$user" staged rc
  printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$user" > "$candidate" || return 1
  # Always validate before replacing the current rule or deleting older rules.
  platform_root /usr/sbin/visudo -cf "$candidate" >/dev/null || return 1
  # sudoers directories and 0440 files are commonly unreadable to the user.
  # Distinguish a real mismatch from a privileged inspection failure.
  if platform_root bash -s -- "$candidate" "$dest" <<'INSPECT'
candidate=$1 dest=$2
if [ -L "$dest" ] || [ ! -e "$dest" ]; then exit 1; fi
if [ ! -f "$dest" ]; then echo "Cannot replace non-file sudo policy: $dest" >&2; exit 2; fi
state=$(stat -c '%a:%u:%g' "$dest") || exit 2
if cmp -s "$candidate" "$dest"; then
  [ "$state" = '440:0:0' ] && exit 0
  exit 1
else
  rc=$?
  if [ "$rc" -ne 1 ]; then echo "Cannot read sudo policy: $dest" >&2; exit 2; fi
  exit 1
fi
INSPECT
  then
    :
  else
    rc=$?
    [ "$rc" = 1 ] || return "$rc"
    staged="$(platform_root mktemp "$dir/.dotfiles.XXXXXXXX")" || return 1
    if ! platform_root install -m 0440 -o root -g root "$candidate" "$staged" || ! platform_root mv -fT "$staged" "$dest"; then
      platform_root rm -f "$staged"
      return 1
    fi
  fi
  platform_root rm -f -- "$dir/$user" "$dir/99-$user"
}
step 'validated passwordless sudo policy' install_sudo_policy
finish
