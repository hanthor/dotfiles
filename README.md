# dotfiles

Fleet dotfiles and host configuration managed locally by native Bash units, mise and chezmoi. Secrets are fetched from Bitwarden at runtime. Units have platform, profile and privilege gates; a successful apply does not imply every optional component ran.

**Overview, live status and architecture: [reilly.asia/infra](https://reilly.asia/infra/)** · handbook: [reilly.asia/infra/handbook](https://reilly.asia/infra/handbook/)

```bash
just apply        # full apply with secrets
dots              # quick pull + apply without secrets
```

---

## What's included

| Area | What it does |
|------|-------------|
| **Shell** | fish + zsh + tmux configs, shared aliases, SSH client config |
| **Packages** | Homebrew (CLI tools) + Flatpak (desktop apps) |
| **Git** | `~/.gitconfig` with SSH signing, `gh` CLI config |
| **SSH keys** | Per-machine ed25519 keys, synced to/from Bitwarden, cross-machine `authorized_keys` |
| **Tailscale** | Auto-joins the network using a stored auth key |
| **Atuin** | Shell history sync key fetched from Bitwarden |
| **GitHub** | Auth + signing keys registered automatically |
| **GNOME** | Keyboard shortcuts, Ptyxis terminal config |
| **Syncthing** | Systemd user service for file sync |
| **Auto-update** | User systemd timer or laptop login service applies non-secret configuration |

---

## Day-to-day commands

```bash
just apply             # Pull latest + apply (attempts BW unlock)
just apply-nosecrets   # Pull latest + apply without Bitwarden
just dotfiles          # Run the dotfiles unit selection
just packages          # Run the package unit selection
just check             # Request native inspection; coverage is being integrated
just edit-host         # Edit this machine's host_vars
```

Shell aliases available everywhere after first apply:

```bash
dots                   # cd to the repo + just apply-nosecrets
dots-apply             # git pull + just apply (full, with BW unlock)
```

---

## Machines

From `inventory.yml`:

| Name | Group | What |
|------|-------|------|
| kanpur | desktop | Laptop (Bluefin) |
| himachal | desktop | Laptop |
| dilli | desktop | Secondary workstation (Bluefin) |
| kerala | desktop | postmarketOS ARM device (musl, `apk`) |
| mumbai | desktop | Debian VM on the phone (Android Virtualization Framework), `cli-only` |
| punjab | server | EC2 agent box (us-east-1) |
| goa | server | Raspberry Pi 5 (applies locally) |
| vm | server | Local dev VM |
| termux | termux_hosts | Raw Termux layer on the phone (platform-specific unit gates apply) |
| test-fleet-fedora, test-fleet-node2 | test_fleet | KubeVirt test VMs (`machine_profile: vm-test`) |
| matrix, telengana | vps | **Retired** Hetzner VPSes, powered on for burn-in — restart nothing on them |

**Bihar** was recently online but is currently unreachable; its OS and services
are unverified. **Karnataka** runs `projectbluefin/utah:testing` with
`multi-user.target` as its default and is listed in the server inventory.
The home Talos manifests, configs and Bitwarden notes are historical recovery
material, not evidence of their current state. The AWS Talos cluster was
terminated on 2026-10-25.
[Spindle](docs/src/servers/spindle-vps/README.md), an OCI VPS in Frankfurt running
Matrix, standalone LiveKit and the School, Reef and Hub Hives, is not listed in
this inventory. The `llm` group is dormant (commented out in `inventory.yml`).

---

## Security

Repo is public — no secrets in git, ever. Units fetch secrets from Bitwarden at runtime; `--no-secrets` suppresses unit vault access. `just apply-remote` resolves a session on the target and forwards it over SSH using `SendEnv=BW_SESSION`, which the target must accept. Retired `matrix` and `telengana` must not be restarted; the shared unit library skips both before unit work.

---

## Documentation

Full handbook lives in [`docs/`](docs/) and is published at [reilly.asia/infra/handbook](https://reilly.asia/infra/handbook/) — run `just docs` to serve it locally.

- [Home Talos cluster history](docs/src/servers/talos-k8s/cluster.md) — historical configuration and recovery reference
- [Spindle VPS](docs/src/servers/spindle-vps/README.md) — Matrix, LiveKit and Hives on OCI
- [TunaOS AWS cluster handbook](docs/src/servers/aws-k8s/cluster.md) — archived cluster history
- [Adding a new machine](docs/src/onboarding.md)
- [Units and runner](docs/src/units.md) and [component reference](docs/src/roles/)
- [Bitwarden vault setup](docs/src/bitwarden.md)
