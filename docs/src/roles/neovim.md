# neovim

**Tags:** `dotfiles`, `neovim`, `editor`  
**Secrets needed:** No  
**Runs on:** All machines

Deploys Neovim configuration.

## What It Does

1. Creates `~/.config/nvim/` directory structure
2. Deploys init.lua and plugin configuration
3. Installs Lazy.nvim plugin manager and configured plugins

## Key Plugins

- **LSP:** nvim-lspconfig, mason.nvim (language server management)
- **Completion:** nvim-cmp with LuaSnip snippets
- **UI:** Catppuccin theme, lualine statusline, nvim-tree file explorer
- **Editing:** treesitter, comment.nvim, autopairs
- **Git:** gitsigns (inline git blame/diff)
- **Navigation:** telescope.nvim (fuzzy finder)
