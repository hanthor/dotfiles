# dotfiles

Ansible-managed dotfiles for all my machines. One command to bootstrap a fresh machine, `just apply` for day-to-day updates.

## Quick Start

### New machine (from scratch)

```bash
curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh | bash
```

Installs Python, Ansible, clones the repo, asks your machine name, and runs the full playbook.

### New machine (from an existing machine with BW unlocked)

```bash
export BW_SESSION=$(bw unlock --raw)
just add-machine bihar
```

SSHs in, forwards your `BW_SESSION`, and bootstraps everything automatically.

### Day-to-day

```bash
just apply             # Full apply
just apply-nosecrets   # Skip Bitwarden-dependent steps
just dotfiles          # Only shell/git/tmux configs
just packages          # Only Homebrew + Flatpak
just update            # Git pull + apply
just check             # Dry run — see what would change
```

## What's Managed

| Category | What | Condition |
|----------|------|-----------|
| **Homebrew** | Core CLI tools (30+), dev runtimes, AI tooling | All machines / desktop split |
| **Shell** | bash, zsh, fish, tmux, starship, bluefin-cli | All machines |
| **Git** | gitconfig with SSH signing, gh CLI auth | All machines |
| **SSH** | Per-machine ed25519 keys (generated or fetched from BW) | All machines |
| **Bitwarden** | CLI login, vault unlock, session forwarding | All machines |
| **GitHub** | Auth + SSH signing key registration | All machines |
| **Tailscale** | Install + network join via BW auth key | All machines |
| **Flatpak** | 40+ desktop apps from Flathub | Desktop only |
| **GNOME** | Custom keyboard shortcuts via dconf | Desktop only |
| **Zen Browser** | Firefox Sync, Bitwarden extension policy | Desktop only |
| **Syncthing** | Systemd user service for file sync | All machines |
| **Auto-update** | Daily `ansible-pull` via systemd timer | All machines |

## Machines

| Name | Type | Host |
|------|------|------|
| karnataka | Desktop (Bluefin) | karnataka |
| kanpur | Desktop | kanpur |
| himachal | Desktop | himachal |
| dilli | Desktop | dilli |
| goa | Desktop (ARM) | goa |
| bihar | Server (Debian) | bihar |
| matrix | Server | matrix.reilly.asia |
| lkofoss | Server | lkofoss.club |

## Prerequisites

| Service | Why |
|---------|-----|
| **Bitwarden** | SSH keys, GitHub token, Tailscale auth key |
| **Tailscale** | Mesh VPN between all machines |
| **GitHub** | Repo hosting, CLI auth, commit signing |

### Bitwarden Vault Items

| Item Name | Type | Contents |
|-----------|------|----------|
| `<machine>` | SSH Key | Auto-generated per-machine ed25519 key |
| `github-token` | Login | GitHub PAT (`repo`, `read:org`, `workflow`, `admin:public_key`) |
| `tailscale-authkey` | Login | Reusable Tailscale auth key |

> SSH keys are auto-generated on first run if not in Bitwarden, then stored back.

## Fork Guide

1. Fork this repo
2. Edit `inventory.yml` — replace machines with yours
3. Create `host_vars/<machine>.yml` for each
4. Edit `group_vars/all.yml` — your name, email, package lists
5. Set up Bitwarden items (see above)
6. Run: `curl -fsSL https://raw.githubusercontent.com/<you>/dotfiles/master/bootstrap.sh | bash`

## Repo Structure

```
├── bootstrap.sh          # One-command setup for fresh machines
├── Justfile              # Day-to-day commands
├── site.yml              # Main Ansible playbook
├── inventory.yml         # Machine inventory
├── ansible.cfg           # Ansible settings
├── requirements.yml      # Galaxy collection deps
├── group_vars/all.yml    # Shared config (packages, users, etc.)
├── host_vars/            # Per-machine variables
└── roles/
    ├── homebrew/         # Homebrew + brew bundle
    ├── shell/            # bashrc, zshrc, fish, tmux
    ├── git/              # gitconfig + gh CLI config
    ├── sshd/             # AcceptEnv BW_SESSION drop-in
    ├── bitwarden/        # BW login + unlock
    ├── ssh_keys/         # Per-machine SSH key provisioning
    ├── github/           # gh auth + signing key registration
    ├── tailscale/        # Network enrollment
    ├── flatpak/          # Desktop apps (Flathub)
    ├── gnome/            # Keyboard shortcuts
    ├── zen_browser/      # Browser config + extensions
    ├── syncthing/        # File sync service
    └── systemd/          # Auto-update timer
```

## BW_SESSION Forwarding

Unlock Bitwarden once on your main machine, then SSH to any other — the session token forwards automatically via `SendEnv BW_SESSION` (client) and `AcceptEnv BW_SESSION` (server drop-in).

## Security

- Repo is public — **no secrets stored in git**
- All secrets fetched from Bitwarden at runtime
- SSH keys stored as Bitwarden's native SSH Key type
- Commit signing via SSH keys registered with GitHub
