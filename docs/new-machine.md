# Adding a New Machine

## Step 1 — Get SSH working

From any existing machine, copy your SSH key to the new machine:

```bash
ssh-copy-id <newmachine>
```

## Step 2 — Bootstrap

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

## Step 3 — Run secrets phase

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

## Step 4 — Register the machine's inventory

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
