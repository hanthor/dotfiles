# omp

**Unit:** `units/omp.sh` (mise task `unit:omp`; see [Units](../units.md))  
**Tags:** `dotfiles`, `omp` (`just apply-tags omp` runs it after the Ansible pass)  
**Secrets needed:** No for the install and routing; the auth-broker token comes from Bitwarden when the vault is unlocked  
**Runs on:** All supported hosts except raw Termux (the unit prints `SKIPPED: omp has no Android build`)

Installs Oh My Pi's Kiro provider, skills, routing and the fleet auth-broker client config. Homebrew hosts get `omp` and Bun from the `can1357/tap` tap through `just packages`; musl hosts use OMP's checksum-verified binary installer and Bun's installer, run by the unit itself. This is no longer an Ansible role.

## Steps

Each step is independent: a failure prints `FAIL  <step>`, fails the unit, and the later steps still run.

1. `omp installed`: on musl, install `omp` and Bun; elsewhere fail with `omp not installed; run: just packages` if missing. Steps that call `omp` print `skip ... (omp missing)` instead.
2. `skills synced`: copy `roles/pi/files/skills/` to `~/.omp/agent/skills/james/`; make `*.sh`/`*.mjs` executable. (`roles/pi` is skill source data, not an Ansible role.)
3. `claude skill links`: symlink each skill directory into `~/.claude/skills/`.
4. `kiro plugin`: `omp plugin install github:elkibalion/omp-kiro-provider` unless installed.
5. `ccleft` (soft): `go install` the quota probe.
6. `kiro.json`: `~/.config/omp/kiro.json` (kiro-cli ACP fallback on 401/403), creating `~/.config/omp`.
7. `omp-route`: the quota-aware launcher at `~/.local/bin/omp-route`.
8. `routing merged`: deep-merge `units/omp/routing.yml` into `~/.omp/agent/config.yml` with `yq` (lists replace).
9. `broker url`: set `auth.broker.url`; config mode `0600`.
10. `broker token`: set `auth.broker.token` from Bitwarden when the vault is unlocked. If no token ends up in the config the unit prints `PARTIAL: broker token not written ...`.
11. `broker status` (soft): print `omp auth-broker status`.

## Auth broker

`omp auth-broker` is the fleet's credential vault: provider logins live on one broker, and every other host is a client that holds only a URL and a bearer token. The broker runs on the OCI `spindle` VPS as a user unit bound to its Tailscale address, `100.113.75.88:8765`. That unit is created by hand and is **not** managed by this repo.

| Key in `~/.omp/agent/config.yml` | Source |
|---|---|
| `auth.broker.url` | `units/omp/auth-broker.conf` (`OMP_AUTH_BROKER_URL`, spindle's Tailscale address, port 8765) |
| `auth.broker.token` | Bitwarden password item `omp-auth-broker-token` (`OMP_AUTH_BROKER_BW_ITEM`) |

The token is written only when Bitwarden is unlocked; a locked vault or `--no-secrets` leaves the existing token as it is. The config file is `0600`.

To seed the token, run `just seed-omp-broker` on a client with the vault unlocked and SSH access to `ubuntu@100.113.75.88`. It reads the live token over SSH without rotating it and creates or updates the Bitwarden item. `OMP_AUTH_BROKER_SSH` overrides the SSH destination. Then run `just apply-tags omp` on each client and verify with `omp auth-broker status`. If the token is rotated on spindle, seed again and re-apply on the clients.

`DEEPSEEK_API_KEY` and the other provider keys are exposed to the shell by the [`shell-ai` unit](shell_ai.md)'s secret files, not by this unit.

## Kiro authentication

Plugin installation is unattended. OAuth is per user and must be completed on each computer:

```text
omp
/login kiro
```

Complete the browser sign-in, then select `kiro/auto` with `/model kiro/auto`. Kiro is not the default model because the OAuth session does not exist until a user signs in.

## Package source

The OMP Homebrew formula is in `can1357/tap`; Bun comes from Homebrew core. Both are core packages for Homebrew-supported hosts. On musl, the official OMP binary installer verifies its SHA-256 and requires `libgcc` and `libstdc++`. `roles/pi/files/package.json` is tracked by Renovate and protected by `deps-guard`; the unit does not install it.
