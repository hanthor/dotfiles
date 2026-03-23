# dotfiles

Personal dotfiles for James Reilly, managed with [chezmoi](https://chezmoi.io).  
A single command bootstraps any machine: installs Homebrew, packages, shell, SSH keys, GitHub auth, Tailscale, Syncthing, Flatpaks, and GNOME shortcuts.

## What's Managed

| Category | Tool | Notes |
|---|---|---|
| Packages | Homebrew (`Brewfile`) | CLI tools, languages, dev tools |
| Flatpaks | `Flatpakfile` | Desktop apps via Flathub |
| Secrets | Bitwarden CLI | SSH keys, tokens — never stored in git |
| SSH keys | Per-machine ed25519 | Stored in Bitwarden as SSH Key items |
| Cross-machine SSH | `~/.ssh/authorized_keys` | All machine public keys deployed everywhere |
| Git signing | SSH key | Registered with GitHub as signing key |
| Shell | zsh + fish | zsh default, fish for interactive use |
| GNOME shortcuts | dconf | Custom keybindings synced via chezmoi |
| File sync | Syncthing | Runs as systemd user service via Homebrew |
| VPN | Tailscale | Auto-enrolled on init |
| Auto-updates | systemd timer | `chezmoi update` runs daily |

---

## Quick Start (personal machines)

> **Prerequisites:** `curl`, `sudo` access, Bitwarden vault pre-loaded (see [Bitwarden Setup](#bitwarden-vault-setup))

```bash
sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply hanthor
```

You'll be prompted for:
1. **Machine name** — one of: `himachal`, `karnataka`, `dilli`, `kanpur`, `goa`, `bihar`, `matrix`, `lkofoss`
2. **Bitwarden login** — email + master password + 2FA (first time only per machine)

Setup takes ~5–10 minutes. On desktop machines, also:
- Open **Zen Browser** → hamburger → Sign in to Sync → approve on phone
- Click the **Bitwarden extension** → enter master password

### Remote Setup (via Tailscale)

```bash
ssh -t james@<machinename> 'sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply hanthor'
```

---

## Forking & Customizing

This repo is designed to be forked. Here's what you need to change to make it yours.

### Prerequisites

| Tool | Why | Get it |
|---|---|---|
| **GitHub account** | Hosts the repo; `gh` CLI authenticates with it | [github.com](https://github.com) |
| **Bitwarden account** | Stores SSH keys and tokens; never touches git | [bitwarden.com](https://bitwarden.com) |
| **Tailscale account** | Connects machines over a private network | [tailscale.com](https://tailscale.com) |
| `curl` | Downloads chezmoi on first run | pre-installed on most systems |
| `sudo` | Homebrew install, system Flatpak installs | standard Linux |

### 1. Fork the repo

```bash
gh repo fork hanthor/dotfiles --clone --remote
```

### 2. Define your machines

Edit `.chezmoi.toml.tmpl` — replace the machine name list and flags:

```toml
{{- $machineName := promptString "Machine name (your-machine-a/your-machine-b/...)" -}}
[data]
  machineName = {{ $machineName | quote }}
  isDesktop   = {{ has $machineName (list "your-desktop-a" "your-desktop-b") }}
  isArm       = {{ eq $machineName "your-arm-machine" }}
```

### 3. Update personal details

| File | What to change |
|---|---|
| `dot_gitconfig.tmpl` | Your name, email, and SSH signing key path |
| `run_once_05_ssh-keys.sh.tmpl` | Your email in the `allowed_signers` line |
| `dot_ssh/config` | Your machine hostnames and key names |
| `scripts/bw-seed-ssh-keys.sh` | Your machine list and SSH user |

### 4. Populate your Bitwarden vault

See [Bitwarden Vault Setup](#bitwarden-vault-setup) below. Use `scripts/bw-seed-ssh-keys.sh` to automate seeding SSH keys from existing machines.

### 5. Customize packages and apps

- **`Brewfile`** — add/remove CLI tools and VS Code extensions
- **`Flatpakfile`** — add/remove Flatpak apps (desktop-only; system vs user sections)
- **`dot_config/dconf/gnome-keybindings.ini`** — your GNOME keyboard shortcuts (`dconf dump /org/gnome/settings-daemon/plugins/media-keys/ > dot_config/dconf/gnome-keybindings.ini`)

### 6. Bootstrap a machine

```bash
sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply YOUR_GITHUB_USERNAME
```

---

## Bitwarden Vault Setup

Create these items before running `chezmoi init`. The SSH key items use Bitwarden's native **SSH Key** type (not Secure Note).

### SSH Key items (one per machine)

| Item Name | Type | Fields |
|---|---|---|
| `himachal` | **SSH Key** | Private Key, Public Key |
| `karnataka` | **SSH Key** | Private Key, Public Key |
| `dilli` | **SSH Key** | Private Key, Public Key |
| `kanpur` | **SSH Key** | Private Key, Public Key |
| `goa` | **SSH Key** | Private Key, Public Key |
| `bihar` | **SSH Key** | Private Key, Public Key |
| `matrix` | **SSH Key** | Private Key, Public Key |
| `lkofoss` | **SSH Key** | Private Key, Public Key |

To generate and seed all keys at once (requires SSH access to each machine):

```bash
bash scripts/bw-seed-ssh-keys.sh
```

This also registers each key with GitHub and writes `dot_ssh/authorized_keys` so all machines can SSH to each other.

### Other vault items

| Item Name | Type | Value |
|---|---|---|
| `github-token` | Login | Password = GitHub PAT with scopes: `repo`, `read:org`, `workflow`, `admin:public_key` |
| `tailscale-authkey` | Login | Password = Tailscale reusable auth key (from [Tailscale admin](https://login.tailscale.com/admin/settings/keys)) |

> **Tailscale key tip:** Create a reusable, pre-approved auth key so machines join your tailnet without manual approval on each one. Rotate the key after all machines are enrolled.

---

## Day-to-Day Operations

```bash
chezmoi update         # pull latest from git + re-apply
chezmoi diff           # preview changes before applying
chezmoi apply          # apply without pulling
```

### Adding a new app

```bash
# Homebrew
echo 'brew "some-tool"' >> Brewfile
chezmoi re-add Brewfile   # or: cd ~/dotfiles && git add Brewfile && git commit

# Flatpak (desktop only)
echo 'com.example.App' >> Flatpakfile   # under [system] or [user]
```

chezmoi will re-run the install script automatically on next `chezmoi apply` because the file hash changed.

### Adding a GNOME keyboard shortcut

1. Set the shortcut via GNOME Settings
2. Dump the updated config: `dconf dump /org/gnome/settings-daemon/plugins/media-keys/ > ~/dotfiles/dot_config/dconf/gnome-keybindings.ini`
3. Commit and push

### Forcing a script to re-run

`run_once_` scripts only re-run when their content changes. To force one (e.g. after key rotation), bump the comment at the top:

```bash
# rotated 2026-04-01
```

---

## Security Notes

- The repo is public — **no secrets are stored in it**
- All secrets (SSH keys, tokens, auth keys) are fetched from Bitwarden at setup time
- SSH keys are stored as Bitwarden's native SSH Key type — visible only to you
- `dot_ssh/authorized_keys` contains only public keys — safe to commit
