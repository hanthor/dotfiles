#!/usr/bin/env bash
# fonts unit: JetBrains Mono Nerd Font for desktop terminals.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

dir="$HOME/.local/share/fonts"
font="$dir/JetBrainsMono/JetBrainsMonoNerdFont-Regular.ttf"

if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if { [ -e "$dir" ] || [ -L "$dir" ]; } && [ ! -d "$dir" ]; then
    note "FAIL: font directory path is not a directory: $dir"
    exit 1
  fi
  [ -d "$dir" ] || note "CHANGE: create font directory $dir"
  desktop_hint="${DOTFILES_IS_DESKTOP:-$(host_var is_desktop)}"
  case "$desktop_hint" in
    1|true) desktop=1 ;;
    0|false) desktop=0 ;;
    *)
      if ! command -v yq >/dev/null 2>&1; then
        note "FAIL: yq required to inspect desktop membership"
        exit 1
      fi
      export DOTFILES_MACHINE="$MACHINE"
      membership="$(yq '(.all.children.desktop.hosts // {}) | has(strenv(DOTFILES_MACHINE))' "$DOTFILES_DIR/inventory.yml" 2>/dev/null)" || {
        note "FAIL: cannot inspect desktop membership"
        exit 1
      }
      case "$membership" in true) desktop=1 ;; false) desktop=0 ;; *) note "FAIL: invalid desktop membership"; exit 1 ;; esac
      ;;
  esac
  if [ "$desktop" = 0 ]; then
    note "SKIPPED: not a desktop; no font install"
  elif [ -f "$font" ]; then
    note "ok    JetBrains Mono Nerd Font already installed"
  else
    note "CHANGE: download and install JetBrains Mono Nerd Font; refresh font cache"
  fi
  exit 0
fi

step "font directory" mkdir -p "$dir"
if ! is_desktop; then
  note "SKIPPED: not a desktop; no font install"
  finish
fi
if [ -f "$font" ]; then
  note "ok    JetBrains Mono Nerd Font already installed"
  finish
fi

install_font() {
  local tmp rc=0
  tmp="$(mktemp -d)" || return 1
  curl -fsSL https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.zip -o "$tmp/font.zip" \
    && mkdir -p "$dir/JetBrainsMono" \
    && unzip -oq "$tmp/font.zip" -d "$dir/JetBrainsMono" || rc=1
  rm -rf "$tmp"
  return $rc
}
step "install JetBrains Mono Nerd Font" install_font
soft "font cache" fc-cache -f
finish
