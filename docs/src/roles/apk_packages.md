# apk_packages

**Tags:** `system`, `packages`, `apk`  
**Secrets needed:** No  
**Runs on:** All machines (skips if not musl/Alpine)

Installs core packages on Alpine/musl-based systems where Homebrew is unavailable.

## What It Does

1. Detects musl libc (Alpine, postmarketOS) — skips entirely on glibc systems
2. Installs core CLI tools via `apk`: bash, fish, zsh, git, neovim, tmux, ripgrep, fzf, jq, podman, etc.
3. Installs Bitwarden CLI via npm (not available in apk repos)
4. Enables podman and podman.socket system services
5. Adds the user to the `podman` group

## When It's Skipped

On glibc systems (Fedora, Debian, Ubuntu, Bluefin), this role does nothing — Homebrew handles all package management.
