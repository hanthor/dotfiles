#!/bin/sh
# Compile the xterm-ghostty terminfo so SSH sessions from Ghostty keep working ncurses apps.
src="$HOME/.config/shell/ghostty.terminfo"; out="$HOME/.terminfo/x/xterm-ghostty"
command -v tic >/dev/null 2>&1 || { echo "tic not installed; skipping xterm-ghostty terminfo"; exit 0; }
[ -f "$out" ] && [ "$out" -nt "$src" ] && exit 0
tic -x -o "$HOME/.terminfo" "$src"
