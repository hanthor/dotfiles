# Roles Reference

`site.yml` runs in phases controlled by tags:

| Tag | Roles | Needs BW? |
|-----|-------|-----------|
| `system` | sshd | No |
| `packages` | homebrew, flatpak | No |
| `dotfiles` | shell, git | No |
| `secrets` | bitwarden, ssh_keys, github, tailscale | Yes |
| `desktop` | flatpak, gnome, zen_browser | No (desktop only) |
| `services` | syncthing, systemd | No |

---

### `sshd`
Drops a config file into `/etc/ssh/sshd_config.d/` that adds `AcceptEnv BW_SESSION`. This allows your Bitwarden session token to be forwarded over SSH without needing to unlock BW on every machine.

### `homebrew`
Installs Homebrew (if missing) and runs `brew bundle` with a generated `Brewfile`. Packages are split into:
- **`core_brews`** — installed on every machine (CLI tools, shells, etc.)
- **`core_tap_brews`** — tapped packages installed everywhere (e.g. `bluefin-cli`)
- **`desktop_brews`** — only on machines in the `desktop` group

### `shell`
Deploys all shell configs:
- `~/.bashrc` — Homebrew init, bluefin-cli, aliases
- `~/.zshrc` / `~/.zprofile` — same, for zsh (default login shell)
- `~/.config/fish/config.fish` — fish config
- `~/.config/fish/conf.d/aliases.fish` — fish aliases
- `~/.config/shell/aliases.sh` — shared bash/zsh aliases (vim=nvim, git shorthands, k=kubectl, dots, etc.)
- `~/.tmux.conf` — tmux config with vi copy mode and clipboard integration
- `~/.ssh/config` — host aliases with short names, `SendEnv BW_SESSION`

Sets `zsh` (from Homebrew) as the login shell. Ptyxis terminal is configured to use `fish` from Homebrew on desktop machines.

### `git`
Deploys `~/.gitconfig` with:
- Name, email
- SSH commit signing (`~/.ssh/id_ed25519`)
- `~/.ssh/allowed_signers` as the signers file
- `gh` CLI config at `~/.config/gh/config.yml`

### `bitwarden`
Resolves a Bitwarden session token in order:
1. `BW_SESSION` environment variable (forwarded via SSH or set by `just apply`)
2. Cached session at `/tmp/bw_session`

If no session is found, secrets tasks are skipped with a warning. Session is cached to `/tmp/bw_session` for reuse within the same run.

### `ssh_keys` *(secrets)*
Manages `~/.ssh/id_ed25519` on each machine:
1. **Key exists in BW** (`james@<machine>`) → writes it to disk
2. **Key on disk but not BW** → stores it in BW as an SSH Key object
3. **Neither** → generates a new ed25519 key pair → stores in BW

Also:
- Fetches all other machines' public keys from BW → adds to `~/.ssh/authorized_keys`
- Updates `~/.ssh/allowed_signers` for git commit signing

### `github` *(secrets)*
- Refreshes `gh` CLI auth scopes
- Registers `~/.ssh/id_ed25519` with GitHub as both an **authentication key** and a **signing key**

### `tailscale` *(secrets)*
- Installs Tailscale (if needed)
- Fetches the reusable auth key from Bitwarden (`tailscale-authkey`)
- Joins the Tailscale network if not already connected

### `flatpak` *(desktop only)*
Installs flatpak apps from Flathub. Split into:
- **`desktop_flatpaks`** — apps for all desktop machines
- **`user_flatpaks`** — additional per-user apps

### `gnome` *(desktop only)*
Loads custom keyboard shortcuts via `dconf`. Also sets the Ptyxis terminal default profile to use `fish` from Homebrew.

### `zen_browser` *(desktop only)*
Deploys browser policies and extension config for Zen Browser (Firefox-based).

### `syncthing`
Deploys a systemd user service for Syncthing file sync.

### `systemd`
Deploys:
- `dotfiles-update.service` + `dotfiles-update.timer` — pulls and applies dotfiles daily
- `atuin-daemon.service` — keeps Atuin shell history synced in the background
