# Secrets with Bitwarden

All secrets live in [Bitwarden](https://bitwarden.com/) and are resolved at runtime.

## How It Works

1. The `bitwarden` role runs first in the secrets phase
2. It checks for a session token in order: `BW_SESSION` env var → `/tmp/bw_session` → interactive `bw unlock`
3. The session token is cached to `/tmp/bw_session` for reuse
4. All `secrets`-tagged roles read from Bitwarden using this token

## Remote Apply

When running `just apply-remote <host>`:

1. Your local Bitwarden session is forwarded over SSH via `SendEnv BW_SESSION`
2. The `sshd` role configures SSH to accept this environment variable
3. The remote machine uses your session without needing its own Bitwarden unlock

```bash
# The session forwarding is automatic:
just apply-remote himachal
```

## Vault Items

| Bitwarden Item | Type | Used By |
|---------------|------|---------|
| `james@<machine>` | SSH Key | `ssh_keys` role — per-machine ed25519 keys |
| `tailscale-authkey` | Secure Note | `tailscale` role — reusable [Tailscale](https://tailscale.com/) auth key |
| `kubeconfig` | Secure Note | `kube` role — cluster kubeconfig |
| `talosconfig` | Secure Note | `kube` role — Talos cluster config |
| `accounts.firefox.com` | Login | `browser_fxa` role — Firefox Account credentials + TOTP |
| `gh_pat`, `pi_api`, etc. | Secure Note | `shell` role — API keys for CLI tools |

## No Session?

If Bitwarden can't unlock (first run, no BW CLI, etc.), secrets tasks are skipped with a warning. Non-secret roles (system, packages, dotfiles, desktop, most services) run normally.

## Seeding New Secrets

```bash
# Push kubeconfig + talosconfig to Bitwarden from a machine that has them:
just seed-kube
```
