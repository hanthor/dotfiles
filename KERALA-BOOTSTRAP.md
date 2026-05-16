# Bootstrapping Kerala (PostMarketOS)

This guide walks through setting up your PostMarketOS laptop to use the dotfiles Ansible configuration.

## Prerequisites

- PostMarketOS installed and SSH accessible
- Optional: SSH key copied from your main machine (`ssh-copy-id kerala`)

## Step 1: Bootstrap Script (from any machine)

If you have SSH access and can forward your BW_SESSION:

```bash
just add-machine kerala
```

Or directly on Kerala (via SSH or USB connection):

```bash
curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh | bash -s -- --name kerala --type desktop
```

The bootstrap script will:
1. Install Python3 (via `apk`)
2. Install git
3. Install `uv` 
4. Install Ansible via `uv`
5. Clone dotfiles to `~/.local/share/dotfiles`
6. Write machine name to `/etc/dotfiles-machine`
7. Run initial playbook (without secrets)

## Step 2: Configure Ansible on Kerala

Once bootstrap completes, Kerala is ready for Ansible runs.

## Step 3: Apply Full Configuration (with Secrets)

On Kerala, unlock your Bitwarden vault and run:

```bash
cd ~/.local/share/dotfiles
just apply
```

Or with environment variable:

```bash
BW_SESSION=$(bw unlock --raw) just apply
```

This will:
- Prompt for Bitwarden unlock
- Generate SSH key pair (or fetch from BW)
- Set up Git, Shell, SSH, Tailscale, etc.
- Skip PostMarketOS-incompatible roles (Flatpak, GNOME, etc.)

## Step 4: Verify Setup

Check that core tools are installed:

```bash
which fish zsh bash git nvim tmux
which tailscale
tailscale status
```

## PostMarketOS-Specific Notes

### Package Management

Kerala uses **`apk`** (Alpine Linux package manager) instead of Homebrew:

```bash
apk add <package>
apk update && apk upgrade
```

The Homebrew role will automatically detect musl libc and skip installation.

### Core Configuration Applied

These roles **will** run on Kerala:

- ✅ `shell` — Fish, Bash, Zsh, Aliases
- ✅ `git` — Git config, SSH signing
- ✅ `ssh_keys` — SSH key provisioning + authorized_keys
- ✅ `sshd` — SSH server config
- ✅ `neovim` — Editor configuration
- ✅ `github` — GitHub SSH key registration
- ✅ `tailscale` — VPN enrollment
- ✅ `bitwarden` — Secrets management
- ✅ `systemd` — Auto-update timer + Atuin daemon
- ✅ `syncthing` — File sync (optional, useful for mobile)

### Roles Skipped

These roles are **not** applicable to PostMarketOS:

- ❌ `flatpak` — Flatpak not available on Alpine
- ❌ `gnome` — GNOME not typically on PostMarketOS (uses Phosh/mobile DE)
- ❌ `zen_browser` — Too heavy for mobile; use default browser
- ❌ `homepage` — Not relevant for mobile device
- ❌ `cockpit` — System dashboard not needed on mobile
- ❌ `lima` — Container VM not needed on mobile
- ❌ `monitoring` — Grafana/monitoring not relevant
- ❌ `proxy` — Caddy reverse proxy not needed
- ❌ `homebrew` — Alpine uses `apk`; auto-detected and skipped

### Day-to-Day Commands

After setup, use:

```bash
just apply              # Full sync with secrets
just apply-nosecrets    # Quick sync without BW
just check              # Dry run
dots                    # git pull + apply-nosecrets (shell alias)
dots-secrets            # git pull + full apply (shell alias)
```

## Troubleshooting

### Ansible not found

If Ansible isn't installed after bootstrap:

```bash
uv tool install ansible
```

### SSH key generation fails

If SSH key provisioning fails, manually generate and add to BW:

```bash
ssh-keygen -t ed25519 -C "james@kerala" -f ~/.ssh/id_ed25519 -N ""
# Then store in BW as SSH Key named "james@kerala"
```

### Tailscale won't join

Ensure the auth key in Bitwarden (`tailscale-authkey`) is valid:

```bash
tailscale logout
# Re-run playbook or manually: tailscale up --auth-key <key>
```

### Python3 not installing

If `apk add python3` fails, try updating package list first:

```bash
sudo apk update
sudo apk add python3
```

## Next Steps

Once Kerala is fully configured:

1. **Commit to git** — Add Kerala to your dotfiles repo if not already done:
   ```bash
   cd ~/.local/share/dotfiles
   git add host_vars/kerala.yml group_vars/all.yml
   git commit -m "Add kerala (PostMarketOS) to managed machines"
   git push
   ```

2. **Enable auto-sync** — Start the dotfiles update timer:
   ```bash
   systemctl --user enable dotfiles-update.timer
   systemctl --user start dotfiles-update.timer
   ```

3. **Test syncthing** — If you enabled file sync:
   ```bash
   syncthing
   # Visit http://localhost:8384 to configure
   ```

4. **Set up Atuin history sync** — Shell history will sync automatically via Atuin daemon.

---

For full documentation, see the main [README.md](README.md).
