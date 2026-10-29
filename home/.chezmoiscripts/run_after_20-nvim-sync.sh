#!/bin/sh
# Best effort: retry bootstrap/sync until it succeeds, then only on config changes.
command -v nvim >/dev/null 2>&1 || exit 0
config="$HOME/.config/nvim"
[ -d "$config" ] || exit 0
lazy="$HOME/.local/share/nvim/lazy/lazy.nvim"
state="$HOME/.cache/dotfiles/nvim-config.cksum"
# Include names as well as contents so additions, deletions and renames count.
fingerprint=$(find "$config" -type f -name '*.lua' -exec cksum {} \; | LC_ALL=C sort | cksum)
if [ -d "$lazy" ] && [ -f "$state" ] && [ "$(cat "$state")" = "$fingerprint" ]; then
  exit 0
fi
[ -d "$lazy" ] || git clone --filter=blob:none https://github.com/folke/lazy.nvim.git --branch=stable "$lazy" || exit 0
if timeout 300 nvim --headless "+Lazy! sync" +qa; then
  mkdir -p "$(dirname "$state")" && printf '%s\n' "$fingerprint" > "$state"
fi
exit 0
