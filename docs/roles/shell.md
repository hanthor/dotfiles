# shell

**Tags:** `dotfiles`, `shell`  
**Secrets needed:** No (except API key deploys from Bitwarden cache)  
**Runs on:** All machines

Deploys all shell configuration files and terminal setup.

## What It Does

### Shell Configs

| File | Purpose |
|------|---------|
| `~/.bashrc` | Homebrew init, bluefin-cli PATH, aliases |
| `~/.zshrc` | Same content, for zsh |
| `~/.zprofile` | zsh login shell profile |
| `~/.config/fish/config.fish` | Fish shell config |
| `~/.config/fish/conf.d/aliases.fish` | Fish aliases |
| `~/.config/shell/aliases.sh` | Shared bash/zsh aliases |

### Common Aliases

- `vim` → `nvim`
- `k` → `kubectl`
- `dots` → git pull + `just apply-nosecrets`
- `dots-secrets` → git pull + `just apply` (with BW)

### Terminal Setup

- Deploys `~/.tmux.conf` with vi copy mode and clipboard integration
- Sets zsh (from Homebrew) as the login shell
- Configures Ptyxis terminal to use `fish` from Homebrew on desktop machines
- Installs JetBrains Mono Nerd Font

### SSH Config

Deploys `~/.ssh/config` with short host aliases for all machines, including `SendEnv BW_SESSION` for Bitwarden session forwarding.

### Files Deployed

- `~/.config/shell/` — aliases and shared config
- `~/.config/fish/` — fish shell config and completions
- `~/.config/starship.toml` — Starship prompt config
- `~/.config/atuin/` — Atuin shell history config
- `~/.ssh/config` — SSH host aliases
- `~/.tmux.conf` — tmux config
