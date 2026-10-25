# neovim

**Unit:** `chezmoi` (`units/chezmoi.sh`; see [Units](../units.md))  
**Tags:** `dotfiles`, `neovim`, `editor`  
**Secrets needed:** No  
**Runs on:** All machines with `chezmoi` installed

[Neovim](https://neovim.io/) configuration, deployed from `home/dot_config/nvim/` (`init.lua`, `lua/config/`, `lua/plugins/`) by chezmoi. After each apply, `.chezmoiscripts/run_after_20-nvim-sync.sh` bootstraps lazy.nvim and runs `nvim --headless "+Lazy! sync" +qa` (best effort, 300 s timeout, never fails the apply).

## Key Plugins

- **[LSP](https://microsoft.github.io/language-server-protocol/):** nvim-lspconfig, [mason.nvim](https://github.com/williamboman/mason.nvim) (language server management)
- **Completion:** nvim-cmp with LuaSnip snippets
- **UI:** Catppuccin theme, lualine statusline, nvim-tree file explorer
- **Editing:** [treesitter](https://tree-sitter.github.io/), comment.nvim, autopairs
- **Git:** gitsigns (inline git blame/diff)
- **Navigation:** telescope.nvim (fuzzy finder)
