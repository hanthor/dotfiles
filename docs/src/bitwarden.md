# Secrets with Bitwarden

All secrets live in [Bitwarden](https://bitwarden.com/) and are resolved at runtime.

## How It Works

1. `just apply` uses `scripts/bw-resolve.sh local` to resolve a session from the environment, `/tmp/bw_session`, or an interactive unlock.
2. The recipe validates the session and runs `bw sync` with a 15-second timeout before invoking `scripts/run-units.sh`. If resolution or sync fails it continues with `--no-secrets`.
3. Unit helpers validate `BW_SESSION` or `/tmp/bw_session` noninteractively, and honor `UNITS_NO_SECRETS=1`. Units handle unavailable sessions and items independently; inspect their `SKIPPED` and `PARTIAL` output.

For `just apply-tags` with a secret-bearing tag such as `kube`, `ai`, `omp`, `shell` or `dotfiles`, the recipe resolves and syncs a session before running. If this fails it runs the selected units with secrets disabled and returns nonzero. Unrelated tags do not prompt.

## Remote Apply

`just apply-remote <host>` resolves a session on the target. `just apply-remote-tags <host> <tags>` does so only for explicitly secret-bearing tags:

1. When resolution is needed, it runs `scripts/bw-resolve.sh remote <host>`, which unlocks Bitwarden **on the
   remote** and prints that host's session token. If the remote CLI is logged
   out it tries `bw login --apikey` with the `bw-api-key` item from your local
   vault; to unlock it pipes the master password (item `James Bitwarden`) over
   stdin, falling back to an interactive `bw unlock` over `ssh -t`.
2. Sends a resolved remote session through SSH `SendEnv=BW_SESSION`, not in the command line. The target SSH daemon must accept `BW_SESSION`; if it rejects a resolved session, the apply aborts. `apply-remote` also atomically replaces the remote's `/tmp/bw_session` with a mode-0600 file; it never writes through an existing symlink and aborts if caching fails. Bootstrap uses the same private replacement when caching a validated session.
3. The remote full apply, or a targeted apply with a secret-bearing tag, resolves and syncs a session before invoking native units. Other targeted applies do not prompt for one.

**Caveat:** sessions are host-specific. If remote resolution fails, the target apply still attempts its own local session resolution and sync; if that fails, it runs units with secrets disabled, and targeted secret applies return nonzero. Each unit determines how to preserve or report existing data; consult its reference.

## Vault Items

Common items consumed by units and scripts (the unit sources and their configuration are authoritative):

| Bitwarden Item | Type | Used By |
|---------------|------|---------|
| `<login>@<machine>` | SSH Key | `ssh-keys` unit — per-machine ed25519 keys |
| `tailscale-apikey` | Login (password) | `tailscale` unit — join and stale-device API cleanup |
| `kubeconfig-karnataka-k3s` | Secure note (`notes` field) | `kube` unit — active Karnataka K3s credentials, context `karnataka-k3s`, merged as the fleet default |
| `kubeconfig`, `talosconfig` | Secure notes | `kube` unit — retained home Talos recovery credentials; never repurpose for K3s |
| `kubeconfig-aws-migration`, `talosconfig-aws-migration` | Secure notes | `kube` unit — retained credentials for the terminated AWS cluster |
| `accounts.firefox.com` | Login + TOTP | `browser-fxa` unit — Firefox Account credentials |
| `github-token` | Login (password) | `github` unit — PAT for `gh` |
| `atuin.sh` | Login + custom field `key` | `atuin` unit — history sync |
| `deepseek-api-key`, `tavily-api-key` | Login (password) | `shell-ai` unit — shell environment |
| `forgejo`, `meta-api-key`, `kiro-api-key` | Secure notes | `shell-ai` unit — shell environment (`forgejo` has an `API Token:` line) |
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
# Push retained home-only configs to their historical Bitwarden notes:
just seed-kube
```

`seed-kube` reads `~/.kube/config-home-talos` and `~/.talos/config`, not the
merged K3s default `~/.kube/config`. It only handles the two retained home
Talos notes. The `*-aws-migration` notes remain recovery material maintained
by hand; the separate `kubeconfig-karnataka-k3s` note is provisioned privately
from the current K3s server. See the [kube unit](roles/kube.md#bitwarden-contract)
for its exact format. Do not upload active K3s credentials into historical notes.
