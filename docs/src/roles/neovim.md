# neovim

**Tags:** `dotfiles`, `neovim`, `editor`  
**Secrets needed:** No  
**Runs on:** All machines

Deploys [Neovim](https://neovim.io/) configuration.

## What It Does

1. Creates `~/.config/nvim/` directory structure
2. Deploys init.lua and plugin configuration
3. Installs Lazy.nvim plugin manager and configured plugins

## Key Plugins

- **[LSP](https://microsoft.github.io/language-server-protocol/):** nvim-lspconfig, [mason.nvim](https://github.com/williamboman/mason.nvim) (language server management)
- **Completion:** nvim-cmp with LuaSnip snippets
- **UI:** Catppuccin theme, lualine statusline, nvim-tree file explorer
- **Editing:** [treesitter](https://tree-sitter.github.io/), comment.nvim, autopairs
- **Git:** gitsigns (inline git blame/diff)
- **Navigation:** telescope.nvim (fuzzy finder)
