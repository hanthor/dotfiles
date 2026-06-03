# homebrew

**Tags:** `packages`, `homebrew`  
**Secrets needed:** No  
**Runs on:** All glibc machines (skipped on musl/Alpine)

Installs and manages Homebrew packages on Linux.

## What It Does

1. Installs Homebrew to `/home/linuxbrew/.linuxbrew` if missing
2. Generates a `Brewfile` from `group_vars/all.yml` package lists
3. Runs `brew bundle` to install/update all packages
4. Ensures Python `packaging` module is available (required by Ansible's systemd module)

## Package Categories

| Variable | Where Defined | Scope |
|----------|--------------|-------|
| `core_brews` | `group_vars/all.yml` | All machines |
| `core_tap_brews` | `group_vars/all.yml` | All machines (tapped) |
| `desktop_brews` | `group_vars/all.yml` | Desktop group only |

## Key Packages

- **Shells:** fish, zsh, bash-preexec
- **CLI tools:** neovim, tmux, direnv, just, make, ripgrep, fzf, eza, bat, fd, zoxide
- **Bluefin extras:** atuin, starship, carapace, tealdeer (via `bluefin-cli`)
- **Dev tools:** go, kubernetes-cli, helm, k9s, podman-compose, ansible, uv
- **AI/ML:** ollama, ramalama, openai-whisper, pi-coding-agent

## Notes

- Homebrew on Linux installs to `/home/linuxbrew/.linuxbrew` — no root needed
- The playbook adds `brew_bin` to `PATH` for all subsequent tasks
