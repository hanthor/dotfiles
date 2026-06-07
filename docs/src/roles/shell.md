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
- `dots-apply` → git pull + `just apply` (with BW)

### Terminal Setup

- Deploys `~/.tmux.conf` with vi copy mode and clipboard integration
- Sets zsh (from [Homebrew](https://brew.sh/)) as the login shell
- Configures Ptyxis terminal to use `fish` from Homebrew on desktop machines
- Installs JetBrains Mono Nerd Font

### SSH Config

Deploys `~/.ssh/config` with short host aliases for all machines, including `SendEnv BW_SESSION` for Bitwarden session forwarding.

### Files Deployed

- `~/.config/shell/` — aliases and shared config
- `~/.config/fish/` — fish shell config and completions
- `~/.config/starship.toml` — [Starship](https://starship.rs/) prompt config
- `~/.config/atuin/` — [Atuin](https://atuin.sh/) shell history config
- `~/.ssh/config` — SSH host aliases
- `~/.tmux.conf` — tmux config

## Per-host secrets (Atuin / DeepSeek / Forgejo)

Three BW-gated blocks deploy host-local credential files. All are wrapped in `when: bw_unlocked` and never wipe existing files on a locked vault:

| BW item | Destination | When |
|---|---|---|
| `atuin.sh` (login + `key` field) | `atuin login` to sync history (no file written; atuin manages its own state) | Only when `atuin status` says not logged in |
| `deepseek-api-key` (password) | `~/.pi/agent/auth.json` (mode 0600) | When the item exists; otherwise the previous file is preserved |
| `forgejo` (note containing `API Token: <pat>`) | `~/.config/shell/secrets.sh` (mode 0600, exports `FORGEJO_TOKEN`) | When the note has a usable token |

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `dots` shell abbreviation doesn't exist after first apply | Fish/zsh hasn't re-read aliases yet | `exec fish` or open a new terminal |
| `atuin` not syncing on this host | Vault locked at apply time and no prior key on disk | Unlock BW, run `dots-apply` |
| Login shell didn't change to zsh | `chsh` required a sudo prompt that the role didn't catch | `chsh -s $(brew --prefix)/bin/zsh` manually |

## How to verify

```bash
echo $SHELL                       # should be the homebrew zsh path
which dots                        # should be a function/alias, not "not found"
atuin status                      # should say "[Sync] active" on hosts that signed in
```
