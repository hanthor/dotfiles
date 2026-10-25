# shellcheck shell=bash
# Shared helpers for units/*.sh. Source this; do not execute it.
# Units use `set -uo pipefail` and never `set -e`: a failing step is recorded
# and the later independent steps still run.
# Homebrew tools come last so a stub or an earlier install wins; BREW_PREFIX is overridable for tests.
PATH="$PATH:${BREW_PREFIX:-/home/linuxbrew/.linuxbrew}/bin"
UNIT_FAILED=0
step() { local d="$1"; shift; if "$@"; then echo "ok    $d"; else echo "FAIL  $d (exit $?)"; UNIT_FAILED=1; fi; }
soft() { local d="$1"; shift; if "$@"; then echo "ok    $d"; else echo "warn  $d (exit $?, ignored)"; fi; }
finish() { [ "$UNIT_FAILED" = 0 ] || exit 1; exit 0; }   # failed steps fail the unit; everything else is exit 0
note() { echo "$*"; }                                    # e.g. note "PARTIAL: vault locked, broker token not written"
install_if_changed() { # src dest mode
  if [ -f "$2" ] && cmp -s "$1" "$2"; then chmod "$3" "$2"; return 0; fi
  mkdir -p "$(dirname "$2")" && install -m "$3" "$1" "$2"
}
DOTFILES_DIR="${DOTFILES_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
IS_TERMUX=0; [ -d /data/data/com.termux/files/usr ] && IS_TERMUX=1
IS_MUSL=0; { [ -e /lib/ld-musl-x86_64.so.1 ] || [ -e /lib/ld-musl-aarch64.so.1 ]; } && IS_MUSL=1
# bw_session: print a usable Bitwarden session or nothing. Never prompts.
bw_session() {
  [ "${UNITS_NO_SECRETS:-0}" = 1 ] && return 0
  command -v bw >/dev/null 2>&1 || return 0
  local s="${BW_SESSION:-}"
  [ -n "$s" ] || { [ -s /tmp/bw_session ] && s="$(cat /tmp/bw_session)"; }
  [ -n "$s" ] && bw unlock --check --session "$s" >/dev/null 2>&1 && printf '%s' "$s"
  return 0
}
MACHINE="${DOTFILES_MACHINE:-$(cat /etc/dotfiles-machine 2>/dev/null || hostname)}"
# host_var KEY [DEFAULT]: KEY from host_vars/$MACHINE.yml (flat `key: value` lines only).
host_var() {
  local v
  v="$(sed -n "s/^$1:[[:space:]]*\([^#]*[^#[:space:]]\).*/\1/p" "$DOTFILES_DIR/host_vars/$MACHINE.yml" 2>/dev/null | head -n1)"
  v="${v//[\"\']/}"
  printf '%s' "${v:-${2:-}}"
}
# is_desktop: DOTFILES_IS_DESKTOP, else host_vars `is_desktop`, else membership of the inventory `desktop` group.
is_desktop() {
  local o="${DOTFILES_IS_DESKTOP:-}"
  [ -n "$o" ] || o="$(host_var is_desktop)"
  case "$o" in 1|true) return 0 ;; 0|false) return 1 ;; esac
  command -v yq >/dev/null 2>&1 || return 1
  [ "$(yq ".all.children.desktop.hosts | has(\"$MACHINE\")" "$DOTFILES_DIR/inventory.yml" 2>/dev/null)" = true ]
}
# skipped_by_profile FLAG: true when this host opted out (host_vars FLAG: true) or is a vm-test machine.
skipped_by_profile() {
  [ "$(host_var "$1")" = true ] || [ "$(host_var machine_profile)" = vm-test ]
}
# write_atomic dest: stdin -> temp file in the same directory (mode 0600) -> mv
write_atomic() {
  local dest="$1" tmp
  mkdir -p "$(dirname "$dest")" || return 1
  tmp="$(umask 077; mktemp "$dest.XXXXXX")" || return 1
  if cat > "$tmp" && chmod 600 "$tmp" && mv -f "$tmp" "$dest"; then return 0; fi
  rm -f "$tmp"; return 1
}
