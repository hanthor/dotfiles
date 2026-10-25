#!/usr/bin/env bash
# fonts unit: JetBrains Mono Nerd Font for desktop terminals.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

dir="$HOME/.local/share/fonts"
font="$dir/JetBrainsMono/JetBrainsMonoNerdFont-Regular.ttf"

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
