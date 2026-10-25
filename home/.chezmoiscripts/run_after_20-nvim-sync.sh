#!/bin/sh
# Best effort: bootstrap lazy.nvim and sync plugins; never fails the apply.
command -v nvim >/dev/null 2>&1 || exit 0
lazy="$HOME/.local/share/nvim/lazy/lazy.nvim"
[ -d "$lazy" ] || git clone --filter=blob:none https://github.com/folke/lazy.nvim.git --branch=stable "$lazy" || true
timeout 300 nvim --headless "+Lazy! sync" +qa 2>&1 | tail -5
exit 0
