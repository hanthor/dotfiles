# Secrets with Bitwarden

All secrets live in [Bitwarden](https://bitwarden.com/) and are resolved at runtime.

## How It Works

1. The `bitwarden` role runs first in the secrets phase.
2. The apply wrapper can prompt via `scripts/bw-resolve.sh`; the role itself reads `BW_SESSION` from the environment, then falls back to `/tmp/bw_session`.
3. It runs `bw sync` (with a 15 s hard timeout, so a flaky vault server can't hang the play) to refresh the local cached vault.
4. It calls `bw status` and sets a `bw_unlocked` host fact: `true` only if the CLI is installed, a session was resolved, *and* the vault actually unlocks.
5. Every BW-using role gates on `when: bw_unlocked | default(false)`. The end-of-play `post_tasks` summary prints one of:
   - `vault unlocked — all secret roles executed normally`
   - `Bitwarden vault was LOCKED — … skipped. To enable: bw unlock …`
   - `SKIPPED (--skip-tags secrets). Run dots-apply to include …`

For `just apply-tags` with an explicit secret-bearing tag such as `kube`, `ai` or `omp`, the wrapper validates and syncs a session before running, and adds the `bitwarden` tag so legacy secret roles receive `bw_unlocked`. It skips secret work and returns non-zero if the session or sync fails; unrelated tags do not prompt.

## Remote Apply

`just apply-remote <host>` (and `just apply-remote-tags <host> <tags>`):

1. Runs `scripts/bw-resolve.sh remote <host>`, which unlocks Bitwarden **on the
   remote** and prints that host's session token. If the remote CLI is logged
   out it tries `bw login --apikey` with the `bw-api-key` item from your local
   vault; to unlock it pipes the master password (item `James Bitwarden`) over
   stdin, falling back to an interactive `bw unlock` over `ssh -t`.
2. Runs `ssh -t <host> "export BW_SESSION='…'; …; just apply"` — the session
   is exported inline in the remote command, not via `SendEnv`. `apply-remote`
   also caches it in the remote's `/tmp/bw_session`.
3. The `bitwarden` role on the remote runs `bw status`: if it reports
   `unlocked`, `bw_unlocked` flips to true and secrets work proceeds.

**Caveat — session portability is not guaranteed.** A `BW_SESSION` token is only valid on the machine that unlocked it — that's why the recipes unlock on the remote instead of forwarding yours. If the remote unlock fails, the remote `bw status` returns `locked`, the role prints a one-line warning, and every BW-touching task is skipped cleanly — nothing fails, no files get clobbered with empty values. Unlock the vault directly on that host (`bw unlock`, then write the session to `/tmp/bw_session`) to enable secrets there.

## Vault Items

Every item a role or script reads (grep `bw get` / `bw list` under `roles/` and `scripts/`):

| Bitwarden Item | Type | Used By |
|---------------|------|---------|
| `james@<machine>` | SSH Key | `ssh_keys` role — per-machine ed25519 keys |
| `tailscale-apikey` | Login (password) | `tailscale` role — key for `tailscale up --authkey` and stale-device cleanup via the API |
| `kubeconfig` | Secure Note | `kube` role — home cluster kubeconfig |
| `talosconfig` | Secure Note | `kube` role — home cluster Talos config |
| `kubeconfig-aws-migration` | Secure Note | `kube` role — AWS cluster kubeconfig |
| `talosconfig-aws-migration` | Secure Note | `kube` role — AWS cluster Talos config |
| `accounts.firefox.com` | Login + TOTP | `browser_fxa` role — Firefox Account credentials |
| `github-token` | Login (password) | `github` role — PAT for `gh auth login` |
| `atuin.sh` | Login + custom field `key` | `atuin` unit — atuin sync login + mnemonic |
| `deepseek-api-key` | Login (password) | `shell-ai` unit — pi `auth.json` |
| `forgejo` | Secure Note (`API Token:` line) | `shell-ai` unit — `FORGEJO_TOKEN` |
| `tavily-api-key` | Login (password) | `shell-ai` unit — `TAVILY_API_KEY` |
| `forgejo.manatee-basking.ts.net` | Login | `forgejo_registry` role — podman registry login |
| `bw-api-key` | Login | `scripts/bw-resolve.sh` — `bw login --apikey` on a remote |
| `James Bitwarden` | Login | `scripts/bw-resolve.sh` — non-interactive unlock on a remote |

## Running Without Secrets

For fast iteration that doesn't need the vault — packages, dotfiles, desktop config — use the explicit no-secrets path:

```bash
just apply-nosecrets   # git pull + apply with --skip-tags secrets
dots                   # alias: cd to the repo + just apply-nosecrets
```

The daily systemd timer (`dotfiles-update.service`) calls `apply-nosecrets`: Ansible skips secret-tagged roles and units receive `--no-secrets`, even if a cached session exists.

## No Session?

If Bitwarden can't unlock (first run, no BW CLI installed, vault genuinely locked on this host), `just apply` skips secret work and continues with non-secret configuration. A targeted secret apply (`just apply-tags`) also continues non-secret work but exits non-zero, so the requested secret update is not mistaken for success.

## Seeding New Secrets

```bash
# Push kubeconfig + talosconfig (home cluster) to Bitwarden from a machine that has them:
just seed-kube
```

`seed-kube` only handles the two home-cluster notes; the `*-aws-migration`
notes are maintained by hand.
