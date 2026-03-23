# dotfiles

Ansible-managed dotfiles for all my machines. One command to bootstrap a fresh machine, `just apply` for day-to-day updates. No central server — every machine manages itself locally.

---

## Adding a New Machine

### Step 1 — Get SSH working

From any existing machine, copy your SSH key to the new machine:

```bash
ssh-copy-id <newmachine>
```

Or if you can only reach it with a password initially, SSH in and complete setup manually.

### Step 2 — Bootstrap

From any existing machine (with `BW_SESSION` unlocked):

```bash
just add-machine <newmachine>
```

This SSHs in, forwards your BW session, and runs the bootstrap script automatically.

Or directly on the new machine:

```bash
curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh | bash -s -- --name <newmachine>
```

The bootstrap script:
1. Installs `uv` (via astral.sh)
2. Installs `ansible-core` + `ansible` via `uv tool install`
3. Clones this repo to `~/.local/share/dotfiles`
4. Writes the machine name to `/etc/dotfiles-machine`
5. Runs the playbook **without secrets** (no Bitwarden needed yet)

### Step 3 — Run secrets phase

Once you have an interactive shell on the new machine:

```bash
just apply
```

This will:
- Prompt for your Bitwarden master password to unlock the vault
- Generate an SSH key pair at `~/.ssh/id_ed25519` (or fetch from BW if it exists)
- Store the new key in Bitwarden as `james@<machine>` (SSH Key type)
- Fetch all other machines' public keys from BW → add to `~/.ssh/authorized_keys`
- Register the key with GitHub (auth + signing)
- Join Tailscale using the auth key from Bitwarden
- Sync the Atuin history key from Bitwarden

### Step 4 — Register the machine's inventory

Add the new machine to `inventory.yml` and create `host_vars/<machine>.yml`:

```yaml
# inventory.yml — add under desktop: or server:
<newmachine>:
  ansible_host: localhost
  ansible_connection: local
```

```yaml
# host_vars/<newmachine>.yml
---
is_arm: false   # set true for ARM machines
```

Then add it to `group_vars/all.yml` under `machines:`:

```yaml
machines:
  <newmachine>:
    hostname: <newmachine>        # or FQDN if needed
```

Commit and push — all other machines will pick it up on their next `just apply`.

---

## Day-to-Day Usage

```bash
just apply             # Pull latest + full apply (unlocks BW interactively)
just apply-nosecrets   # Pull latest + apply without Bitwarden (fast)
just dotfiles          # Only shell/git/tmux configs
just packages          # Only Homebrew + Flatpak
just check             # Dry run — see what would change
just edit-host         # Edit this machine's host_vars
```

Or use the shell aliases (available everywhere after first apply):

```bash
dots                   # git pull + apply-nosecrets
dots-secrets           # git pull + full apply with BW unlock
```

---

## How It Works

### Architecture

- **No central server** — each machine runs `ansible-playbook --connection=local`
- **Secrets from Bitwarden** — fetched at runtime via `bw` CLI, never stored in git
- **BW_SESSION forwarding** — unlock once on your laptop, SSH to any machine and it forwards automatically via `SendEnv`/`AcceptEnv`
- **Daily auto-sync** — systemd timer pulls and applies changes every day

### Playbook Phases

`site.yml` runs in four phases controlled by tags:

| Tag | Roles | Needs BW? |
|-----|-------|-----------|
| `system` | sshd | No |
| `packages` | homebrew, flatpak | No |
| `dotfiles` | shell, git | No |
| `secrets` | bitwarden, ssh_keys, github, tailscale | Yes |
| `desktop` | flatpak, gnome, zen_browser | No (desktop only) |
| `services` | syncthing, systemd | No |

---

## Roles Reference

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
- **`user_flatpaks`** — additional per-user apps (currently empty)

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

---

## Machines

| Name | Type | Host |
|------|------|------|
| karnataka | Desktop (Bluefin) | karnataka |
| kanpur | Desktop (Bluefin) | kanpur |
| himachal | Desktop | himachal |
| dilli | Desktop | dilli |
| bihar | Server (Debian) | bihar |
| matrix | Server | matrix.reilly.asia |
| lkofoss | Server | lkofoss.club |

---

## Bitwarden Vault Items Required

| Item Name | Type | Contents |
|-----------|------|----------|
| `james@<machine>` | SSH Key | Per-machine ed25519 key pair (auto-created if missing) |
| `atuin.sh` | Login | Atuin sync account + encryption key (see below) |
| `tailscale-authkey` | Login | Reusable Tailscale auth key (password field) |
| `github-token` | Login | GitHub PAT with `admin:public_key`, `admin:ssh_signing_key` scopes |

### Setting up the `atuin.sh` Bitwarden item

If you're using your own [atuin](https://atuin.sh) account, create the item once:

1. Register at <https://app.atuin.sh> (free) and note your username and password.
2. On your first machine, run `atuin login` interactively — this generates `~/.local/share/atuin/key`.
3. Get your encryption key mnemonic: `atuin key`
4. In Bitwarden, create a **Login** item named **`atuin.sh`**:
   - **Username**: your atuin username
   - **Password**: your atuin password
   - **Custom field** (text) named `key`: the mnemonic from `atuin key`

After that, `just apply` on any machine will fetch these credentials and log in automatically.
If the item doesn't exist, the playbook skips atuin login with a warning — nothing breaks.

---

## Repo Structure

```
├── bootstrap.sh          # One-command setup for fresh machines
├── Justfile              # Day-to-day commands
├── site.yml              # Main Ansible playbook (4 phases)
├── inventory.yml         # All machines + desktop/server groups
├── ansible.cfg           # Ansible settings
├── requirements.yml      # Galaxy collection deps (community.general)
├── group_vars/all.yml    # Shared vars: packages, users, machine list
├── host_vars/            # Per-machine overrides (is_arm, etc.)
└── roles/
    ├── sshd/             # AcceptEnv BW_SESSION drop-in
    ├── homebrew/         # Homebrew install + brew bundle
    ├── shell/            # All shell configs + SSH client config
    ├── git/              # gitconfig + gh CLI config
    ├── bitwarden/        # BW session resolution
    ├── ssh_keys/         # SSH key provisioning + authorized_keys
    ├── github/           # gh auth + key registration
    ├── tailscale/        # Network enrollment
    ├── flatpak/          # Desktop apps (Flathub)
    ├── gnome/            # Keyboard shortcuts + Ptyxis config
    ├── zen_browser/      # Browser policies
    ├── syncthing/        # File sync service
    └── systemd/          # Auto-update timer + atuin daemon
```

---

## Security

- Repo is **public** — no secrets in git, ever
- All secrets fetched from Bitwarden at runtime
- SSH keys stored as Bitwarden's native SSH Key type (`james@<machine>`)
- Commit signing via SSH keys registered with GitHub
- BW_SESSION forwarded over SSH, never persisted beyond `/tmp/bw_session`
