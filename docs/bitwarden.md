# Bitwarden Vault Setup

## Required Items

| Item Name | Type | Contents |
|-----------|------|----------|
| `james@<machine>` | SSH Key | Per-machine ed25519 key pair (auto-created if missing) |
| `atuin.sh` | Login | Atuin sync account + encryption key |
| `tailscale-authkey` | Login | Reusable Tailscale auth key (password field) |
| `github-token` | Login | GitHub PAT with `admin:public_key`, `admin:ssh_signing_key` scopes |

SSH key items are created automatically on first `just apply` — you only need to manually create the rest.

## Setting up `atuin.sh`

1. Register at <https://app.atuin.sh> and note your username and password.
2. On your first machine, run `atuin login` interactively — this generates `~/.local/share/atuin/key`.
3. Get your encryption key mnemonic: `atuin key`
4. In Bitwarden, create a **Login** item named **`atuin.sh`**:
   - **Username**: your atuin username
   - **Password**: your atuin password
   - **Custom field** (text) named `key`: the mnemonic from `atuin key`

After that, `just apply` on any machine will fetch these credentials and log in automatically.
If the item doesn't exist, the playbook skips atuin login with a warning — nothing breaks.

## BW_SESSION Forwarding

Unlock BW once on your laptop; the session token forwards automatically to any machine you SSH into via `SendEnv`/`AcceptEnv`. You never need to unlock BW on remote machines interactively.
