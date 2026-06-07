# Secrets with Bitwarden

All secrets live in [Bitwarden](https://bitwarden.com/) and are resolved at runtime.

## How It Works

1. The `bitwarden` role runs first in the secrets phase.
2. It resolves a session token in order: `BW_SESSION` env var → `/tmp/bw_session` → interactive `bw unlock`.
3. It runs `bw sync` (with a 15 s hard timeout, so a flaky vault server can't hang the play) to refresh the local cached vault.
4. It calls `bw status` and sets a `bw_unlocked` host fact: `true` only if the CLI is installed, a session was resolved, *and* the vault actually unlocks.
5. Every BW-using role gates on `when: bw_unlocked | default(false)`. The end-of-play `post_tasks` summary prints one of:
   - `vault unlocked — all secret roles executed normally`
   - `Bitwarden vault was LOCKED — … skipped. To enable: bw unlock …`
   - `SKIPPED (--skip-tags secrets). Run dots-apply to include …`

## Remote Apply

When running `just apply-remote <host>` or `just apply-remote-tags <host> <tags>`:

1. Your local Bitwarden session is forwarded over SSH (via `SendEnv BW_SESSION`).
2. The remote machine writes it to `/tmp/bw_session`.
3. The `bitwarden` role runs `bw status` on the remote: if it reports `unlocked`, `bw_unlocked` flips to true and secrets work proceeds.

**Caveat — session portability is not guaranteed.** A `BW_SESSION` token derived on one machine may be rejected on another because the encrypted vault state, KDF parameters, or vault sync state differ. When that happens, the remote `bw status` returns `locked`, the role prints a one-line warning, and every BW-touching task is skipped cleanly — nothing fails, no files get clobbered with empty values. Unlock the vault directly on that host (`bw unlock`, then write the session to `/tmp/bw_session`) to enable secrets there.

## Vault Items

| Bitwarden Item | Type | Used By |
|---------------|------|---------|
| `james@<machine>` | SSH Key | `ssh_keys` role — per-machine ed25519 keys |
| `tailscale-authkey` | Secure Note | `tailscale` role — reusable [Tailscale](https://tailscale.com/) auth key |
| `kubeconfig` | Secure Note | `kube` role — cluster kubeconfig |
| `talosconfig` | Secure Note | `kube` role — Talos cluster config |
| `accounts.firefox.com` | Login | `browser_fxa` role — Firefox Account credentials + TOTP |
| `gh_pat`, `pi_api`, etc. | Secure Note | `shell` role — API keys for CLI tools |

## Running Without Secrets

For fast iteration that doesn't need the vault — packages, dotfiles, desktop config — use the explicit no-secrets path:

```bash
just apply-nosecrets   # git pull + apply with --skip-tags secrets
dots                   # the same, as a shell alias
```

The daily systemd timer (`dotfiles-update.service`) calls `apply-nosecrets` for the same reason: it can't unlock the vault non-interactively, so it doesn't try.

## No Session?

If Bitwarden can't unlock (first run, no BW CLI installed, vault genuinely locked on this host), every secret-touching task is skipped automatically. Non-secret roles (system, packages, dotfiles, desktop, most services) run normally and the play exits successfully — the end-of-play summary tells you exactly which roles didn't get to do their BW work.

## Seeding New Secrets

```bash
# Push kubeconfig + talosconfig to Bitwarden from a machine that has them:
just seed-kube
```
