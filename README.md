# dotfiles

Ansible-managed dotfiles for every machine I own. One command to go from a fresh install to a fully configured system. No central server — each machine manages itself locally, secrets stay in Bitwarden, and everything stays in sync automatically.

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
| **Auto-update** | Systemd timer pulls and applies changes daily |

---

## Day-to-day commands

```bash
just apply             # Pull latest + full apply (prompts for BW unlock)
just apply-nosecrets   # Pull latest + apply without Bitwarden (fast)
just dotfiles          # Only shell/git/tmux configs
just packages          # Only Homebrew + Flatpak
just check             # Dry run — see what would change
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
| himachal | desktop | Laptop — also drives the Hive (`hive_ops`) |
| dilli | desktop | Secondary workstation (Bluefin) |
| kerala | desktop | postmarketOS ARM device (musl, `apk`) |
| mumbai | desktop | Debian VM on the phone (Android Virtualization Framework), `cli-only` |
| punjab | server | EC2 agent box (us-east-1) |
| goa | server | Raspberry Pi 5 (applies locally) |
| vm | server | Local dev VM |
| termux | termux_hosts | Raw Termux layer on the phone — `termux_packages` only |
| test-fleet-fedora, test-fleet-node2 | test_fleet | KubeVirt test VMs (`machine_profile: vm-test`) |
| matrix, telengana | vps | **Retired** Hetzner VPSes, powered on for burn-in — restart nothing on them |

The home Talos cluster, **bihar** + **karnataka**, is not Ansible-managed: it is
powered down and in storage, expected back. The AWS Talos cluster was terminated
on 2026-10-25. [Spindle](docs/src/servers/spindle-vps/README.md), an OCI VPS in
Frankfurt running Matrix, standalone LiveKit and the School, Reef and Hub Hives,
is not listed in this inventory.
The `llm` group is dormant (commented out in `inventory.yml`).

---

## Security

Repo is public — no secrets in git, ever. All secrets are fetched from Bitwarden at runtime. `just apply-remote` unlocks Bitwarden on the target (via `scripts/bw-resolve.sh remote`) and exports that session inline over `ssh -t`, so you drive every host from one terminal.

---

## Documentation

Full handbook lives in [`docs/`](docs/) and is published at [reilly.asia/infra/handbook](https://reilly.asia/infra/handbook/) — run `just docs` to serve it locally.

- [Talos cluster handbook](docs/src/servers/talos-k8s/cluster.md) — Bihar + Karnataka (home, offline), Lemonade, KubeVirt
- [Spindle VPS](docs/src/servers/spindle-vps/README.md) — Matrix, LiveKit and Hives on OCI
- [TunaOS AWS cluster handbook](docs/src/servers/aws-k8s/cluster.md) — archived cluster history
- [Adding a new machine](docs/src/onboarding.md)
- [Roles reference](docs/src/roles/)
- [Bitwarden vault setup](docs/src/bitwarden.md)
