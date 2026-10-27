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
  [ -n "$s" ] && BW_SESSION="$s" bw unlock --check >/dev/null 2>&1 && printf '%s' "$s"
  return 0
}
MACHINE="$(cat /etc/dotfiles-machine 2>/dev/null || hostname)"
