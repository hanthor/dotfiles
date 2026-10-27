# Secrets with Bitwarden

All secrets live in [Bitwarden](https://bitwarden.com/) and are resolved at runtime.

## How It Works

1. `just apply` uses `scripts/bw-resolve.sh local` to resolve a session from the environment, `/tmp/bw_session`, or an interactive unlock.
2. The recipe validates the session and runs `bw sync` with a 15-second timeout before invoking `scripts/run-units.sh`. If resolution or sync fails it continues with `--no-secrets`.
3. Unit helpers validate `BW_SESSION` or `/tmp/bw_session` noninteractively, and honor `UNITS_NO_SECRETS=1`. Units handle unavailable sessions and items independently; inspect their `SKIPPED` and `PARTIAL` output.

For `just apply-tags` with a secret-bearing tag such as `kube`, `ai` or `omp`, the recipe resolves and syncs a session before running. If this fails it runs the selected units with secrets disabled and returns nonzero. Unrelated tags do not prompt.

## Remote Apply

`just apply-remote <host>` (and `just apply-remote-tags <host> <tags>`):

1. Runs `scripts/bw-resolve.sh remote <host>`, which unlocks Bitwarden **on the
   remote** and prints that host's session token. If the remote CLI is logged
   out it tries `bw login --apikey` with the `bw-api-key` item from your local
   vault; to unlock it pipes the master password (item `James Bitwarden`) over
   stdin, falling back to an interactive `bw unlock` over `ssh -t`.
2. Sends the remote session through SSH `SendEnv=BW_SESSION`, not in the command line. The target SSH daemon must accept `BW_SESSION`; if it rejects a resolved session, the apply aborts. `apply-remote` also caches it in the remote's `/tmp/bw_session`.
3. The remote apply validates and syncs the session before invoking native units. If a resolved session is not accepted over SSH, the remote apply aborts.

**Caveat:** sessions are host-specific. If remote resolution fails, secret-capable units run with secrets disabled; targeted secret applies return nonzero. Unlock Bitwarden on that host and retry. Each unit determines how to preserve or report existing data; consult its reference.

## Vault Items

Common items consumed by units and scripts (the unit sources and their configuration are authoritative):

| Bitwarden Item | Type | Used By |
|---------------|------|---------|
| `<login>@<machine>` | SSH Key | `ssh-keys` unit — per-machine ed25519 keys |
| `tailscale-apikey` | Login (password) | `tailscale` unit — join and stale-device API cleanup |
| `kubeconfig`, `talosconfig` | Secure notes | `kube` unit — home cluster credentials |
| `kubeconfig-aws-migration`, `talosconfig-aws-migration` | Secure notes | `kube` unit — stored AWS cluster credentials |
| `accounts.firefox.com` | Login + TOTP | `browser-fxa` unit — Firefox Account credentials |
| `github-token` | Login (password) | `github` unit — PAT for `gh` |
| `atuin.sh` | Login + custom field `key` | `atuin` unit — history sync |
| `deepseek-api-key`, `tavily-api-key` | Login (password) | `shell-ai` unit — shell environment |
| `forgejo`, `meta-api-key`, `kiro-api-key` | Secure notes | `shell-ai` unit — shell environment |
| `omp-auth-broker-token` | Login (password) | `omp` unit — broker client token (item configurable) |
| `forgejo.manatee-basking.ts.net` | Login | `forgejo-registry` unit — Podman registry login |
| `bw-api-key` | Login | `scripts/bw-resolve.sh` — `bw login --apikey` on a remote |
| `James Bitwarden` | Login | `scripts/bw-resolve.sh` — non-interactive unlock on a remote |

## Running Without Secrets

For fast iteration that doesn't need the vault — packages, dotfiles, desktop config — use the explicit no-secrets path:

```bash
just apply-nosecrets   # git pull + native units with --no-secrets
dots                   # alias: cd to the repo + just apply-nosecrets
```

The systemd update service calls `apply-nosecrets`, so units receive `--no-secrets` even if a cached session exists.

## No Session?

If Bitwarden can't unlock (first run, no BW CLI installed, vault genuinely locked on this host), `just apply` skips secret work and continues with non-secret configuration. A targeted secret apply (`just apply-tags`) also continues non-secret work but exits non-zero, so the requested secret update is not mistaken for success.

## Seeding New Secrets

```bash
# Push kubeconfig + talosconfig (home cluster) to Bitwarden from a machine that has them:
just seed-kube
```

`seed-kube` only handles the two home-cluster notes; the `*-aws-migration`
notes are maintained by hand.
