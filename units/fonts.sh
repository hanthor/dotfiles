#!/usr/bin/env bash
# fonts unit: JetBrains Mono Nerd Font for desktop terminals.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=units/platform-config.bash
. "$DOTFILES_DIR/units/platform-config.bash"

dir="$HOME/.local/share/fonts"
font="$dir/JetBrainsMono/JetBrainsMonoNerdFont-Regular.ttf"
pending="$dir/.dotfiles-jetbrainsmono-cache-pending"

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
  elif [ ! -f "$font" ]; then
    note "CHANGE: download and install JetBrains Mono Nerd Font; refresh font cache"
  elif [ -e "$pending" ]; then
    note "CHANGE: retry JetBrains Mono font cache refresh"
  else
    note "ok    JetBrains Mono Nerd Font already installed"
  fi
  exit 0
fi

step "font directory" sh -c 'mkdir -p "$1" && chmod 0755 "$1"' sh "$dir"
if platform_desktop; then
  :
else
  rc=$?
  if [ "$rc" = 1 ]; then note "SKIPPED: not a desktop; no font install"
  else step "desktop membership" false; fi
  finish
fi
if [ ! -f "$font" ]; then
  install_font() {
    local tmp rc=0
    tmp="$(mktemp -d)" || return 1
    # Extract before touching the destination: a failed unzip must not leave the
    # Regular font behind as a false success marker on the next apply.
    curl -fsSL https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.zip -o "$tmp/font.zip" \
      && mkdir "$tmp/extracted" \
      && unzip -oq "$tmp/font.zip" -d "$tmp/extracted" \
      && [ -f "$tmp/extracted/JetBrainsMonoNerdFont-Regular.ttf" ] \
      && : > "$pending" \
      && mkdir -p "$dir/JetBrainsMono" \
      && chmod 0755 "$dir/JetBrainsMono" \
      && cp -a "$tmp/extracted/." "$dir/JetBrainsMono/" || rc=1
    if [ "$rc" != 0 ] && [ -e "$pending" ]; then rm -f "$font"; fi
    rm -rf "$tmp"
    return "$rc"
  }
  step "install JetBrains Mono Nerd Font" install_font
else
  note "ok    JetBrains Mono Nerd Font already installed"
fi

if [ -f "$font" ] && [ -e "$pending" ]; then
  refresh_font_cache() { fc-cache -f && rm -f "$pending"; }
  step "font cache" refresh_font_cache
fi
finish
