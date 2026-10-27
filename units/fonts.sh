#!/usr/bin/env bash
# fonts unit: JetBrains Mono Nerd Font for desktop terminals.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=units/platform-config.bash
. "$DOTFILES_DIR/units/platform-config.bash"

dir="$HOME/.local/share/fonts"
font="$dir/JetBrainsMono/JetBrainsMonoNerdFont-Regular.ttf"

if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if { [ -e "$dir" ] || [ -L "$dir" ]; } && [ ! -d "$dir" ]; then
    note "FAIL: font directory path is not a directory: $dir"
    exit 1
  fi
  [ -d "$dir" ] || note "CHANGE: create font directory $dir"
  if platform_desktop; then
    desktop=1
  else
    rc=$?
    if [ "$rc" = 1 ]; then desktop=0; else note "FAIL: cannot inspect desktop membership"; exit 1; fi
  fi
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
if platform_desktop; then
  :
else
  rc=$?
  if [ "$rc" = 1 ]; then note "SKIPPED: not a desktop; no font install"
  else step "desktop membership" false; fi
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
