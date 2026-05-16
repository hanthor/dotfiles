# Kerala Ansible Integration - Current Status

## ✅ Completed

### Configuration Changes
- ✅ Added `host_vars/kerala.yml` with PostMarketOS-specific settings:
  - `is_arm: true` (PostMarketOS devices are ARM)
  - `is_postmarketos: true`
  - Skip flags for incompatible desktop roles (flatpak, gnome, zen_browser, etc.)
  
- ✅ Updated `site.yml` playbook:
  - Added `is_postmarketos` fact propagation
  - Added conditional `skip_*` flags to all roles
  - Roles now check for `skip_<role>` before executing
  
- ✅ Added Kerala to `group_vars/all.yml`:
  - Added to `machines:` dict (for SSH config generation)
  - Added to `fleet:` dict with mobile icon

- ✅ Updated inventory (`inventory.yml`):
  - Kerala already present, correctly configured

- ✅ Created `KERALA-BOOTSTRAP.md`:
  - Comprehensive bootstrap guide
  - PostMarketOS-specific notes
  - Troubleshooting section
  - Day-to-day commands

- ✅ Committed all changes to git

### Ansible Configuration Verified
- ✅ `ansible-inventory --host kerala` shows correct settings
- ✅ Kerala appears in online Tailscale peers (reachable at 100.67.142.116)
- ✅ SSH key scanning works: `ssh-keyscan kerala` successful

## ⚠️ Current Blocker: SSH Authentication

When attempting `just add-machine kerala`, SSH auth failed:

```
Permission denied (publickey,password,keyboard-interactive).
Too many authentication failures
```

**Issue:** Your SSH key (`~/.ssh/id_ed25519`) is not yet authorized on Kerala, and we can't do interactive password auth in non-TTY environment.

## 🚀 Next Steps to Complete Bootstrap

### Option A: Bootstrap from Kerala itself (Recommended for first-time setup)

1. **On Kerala**, open terminal and run:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh | bash -s -- --name kerala --type desktop
   ```

2. This will:
   - Install Python3 via `apk add python3`
   - Install git via apk
   - Install `uv` 
   - Install Ansible via `uv tool install ansible`
   - Clone dotfiles to `~/.local/share/dotfiles`
   - Write `/etc/dotfiles-machine`
   - Run initial playbook without secrets

3. Once bootstrap completes, unlock Bitwarden and run full config:
   ```bash
   cd ~/.local/share/dotfiles
   just apply
   ```

### Option B: From existing machine (requires SSH key already set up)

1. First, copy your SSH key to Kerala:
   ```bash
   ssh-copy-id -i ~/.ssh/id_ed25519 root@kerala
   # or if you have a password set:
   ssh -u root kerala  # enter password when prompted
   mkdir -p ~/.ssh
   # paste your public key into ~/.ssh/authorized_keys
   ```

2. Then from your main machine:
   ```bash
   cd ~/.local/share/dotfiles
   just add-machine kerala desktop
   ```

### Option C: Pre-generate SSH key and add to Bitwarden (Advanced)

If you want the automation to handle the SSH key:

1. On Kerala, pre-generate the SSH key:
   ```bash
   ssh-keygen -t ed25519 -C "james@kerala" -f ~/.ssh/id_ed25519 -N ""
   cat ~/.ssh/id_ed25519  # copy to clipboard
   cat ~/.ssh/id_ed25519.pub
   ```

2. In Bitwarden, create an **SSH Key** item named `james@kerala`:
   - Copy the private key
   - Set public key field
   - Save

3. Then the bootstrap will find and use this key automatically.

## What Will Happen After Bootstrap

Once Kerala is bootstrapped, future updates run automatically:

### Daily Auto-Update
- Systemd timer triggers `dotfiles-update.service` daily
- Runs: `git pull && just apply-nosecrets`
- No manual intervention needed
- Secrets are cached in `/tmp/bw_session`

### Role Application on Kerala

**✅ WILL RUN:**
- `sshd` — SSH server config
- `sudo` — Sudo configuration  
- `shell` — Fish, Bash, Zsh, aliases, SSH client config
- `git` — Git config + signing keys
- `neovim` — Editor configuration
- `bitwarden` — BW CLI + session management
- `ssh_keys` — SSH key provisioning + authorized_keys
- `github` — GitHub SSH key registration
- `tailscale` — VPN network join
- `systemd` — Auto-update timer + Atuin daemon
- `syncthing` — File sync service (mobile-friendly)

**❌ WILL SKIP (PostMarketOS incompatible):**
- `homebrew` — Auto-skipped (musl libc detected)
- `flatpak` — Not available on Alpine
- `gnome` — PostMarketOS uses Phosh (mobile DE)
- `zen_browser` — Too heavy; use native browser
- `homepage` — Dashboard not relevant on mobile
- `cockpit` — System management UI not needed
- `lima` — Container VM not needed
- `monitoring` — Grafana/monitoring not relevant
- `proxy` — Caddy reverse proxy not needed

## Testing the Configuration

### Dry-run (without making changes)
Once Kerala has Ansible installed, run:
```bash
cd ~/.local/share/dotfiles
just check  # = ansible-playbook ... --check --diff
```

### Verify Roles Apply Correctly
```bash
ansible-playbook -i inventory.yml site.yml --limit kerala --tags "dotfiles,system" --check
```

### Check Specific Role
```bash
ansible-playbook -i inventory.yml site.yml --limit kerala --tags "shell" -vv
```

## File Manifest

Changes made to dotfiles repo:

```
host_vars/kerala.yml (NEW)
  - PostMarketOS configuration
  - skip_* flags for 9 incompatible roles

site.yml (MODIFIED)
  - Added is_postmarketos fact
  - 9 role conditions updated with skip_* checks

group_vars/all.yml (MODIFIED)
  - Kerala added to fleet (mdi-cellphone icon)
  - Kerala added to machines (for SSH config)

KERALA-BOOTSTRAP.md (NEW)
  - 180+ lines of setup + troubleshooting guide
```

## Security Notes

- ✅ No secrets in git (all from Bitwarden)
- ✅ SSH keys auto-generated or fetched from BW
- ✅ BW session forwarded via SSH, cached to `/tmp/`
- ✅ GitHub token fetched at runtime
- ✅ Tailscale auth key from BW

## Hardware Info for Kerala

From the bootstrap script detection:

```
OS: postmarketos
Package Manager: apk
libc: musl (Alpine-based)
SSH Server: OpenSSH 10.3
Tailscale: Ready (already connected as 100.67.142.116)
```

## Next Immediate Action

**SSH into Kerala and run the bootstrap script:**

```bash
ssh root@kerala  # or use Tailscale IP if DNS isn't configured
curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh | \
  bash -s -- --name kerala --type desktop
```

Then follow up with:
```bash
cd ~/.local/share/dotfiles
just apply  # Unlock BW and apply full config
```

---

For detailed bootstrap instructions, see [`KERALA-BOOTSTRAP.md`](KERALA-BOOTSTRAP.md).
