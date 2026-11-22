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
| himachal | desktop | Laptop |
| dilli | desktop | Secondary workstation (Bluefin) |
| kerala | desktop | postmarketOS ARM device (musl, `apk`) |
| mumbai | desktop | Debian VM on the phone (Android Virtualization Framework), `cli-only` |
| punjab | server | Agent box, KubeVirt VM on karnataka |
| bihar | desktop | Home server (Bluefin): active hive host, KubeStellar hub |
| goa | server | Raspberry Pi 5 (applies locally) |
| vm | server | Local dev VM |
| termux | termux_hosts | Raw Termux layer on the phone — `termux_packages` only |
| test-fleet-fedora, test-fleet-node2 | test_fleet | KubeVirt test VMs (`machine_profile: vm-test`) |
| matrix, telengana | vps | **Retired** Hetzner VPSes, powered on for burn-in — restart nothing on them |

**bihar** and **karnataka** are home servers on Bluefin with separate k3s
clusters linked by KubeStellar (the Talos cluster they ran before is archived).
bihar runs the School, Reef and Hub hives, with karnataka as a cold standby;
karnataka hosts KubeVirt (including punjab), CI runners and the LMS.
[Spindle](docs/src/servers/spindle-vps/README.md), an OCI VPS in Frankfurt, runs
Matrix and LiveKit, is the public front door (Caddy) for the hives and coordinates
their failover; it is not in this inventory. The AWS Talos cluster was terminated
on 2026-10-25. Current state of every host: [Fleet status](docs/src/fleet.md).
The `llm` group is dormant (commented out in `inventory.yml`).

---

## Security

Repo is public — no secrets in git, ever. All secrets are fetched from Bitwarden at runtime. `just apply-remote` unlocks Bitwarden on the target (via `scripts/bw-resolve.sh remote`) and exports that session inline over `ssh -t`, so you drive every host from one terminal.

---

## Documentation

Full handbook lives in [`docs/`](docs/) and is published at [reilly.asia/infra/handbook](https://reilly.asia/infra/handbook/) — run `just docs` to serve it locally.

- [Fleet status](docs/src/fleet.md) — every host, live / intermittent / retired
- [Bihar](docs/src/servers/bihar.md), [Karnataka](docs/src/servers/karnataka.md), [Home k3s + KubeStellar](docs/src/servers/home-k3s.md)
- [Hives hosting and failover](docs/src/servers/hives.md) — bihar primary, karnataka standby, spindle front door
- [Spindle VPS](docs/src/servers/spindle-vps/README.md) — Matrix, LiveKit, Caddy front door on OCI
- [Archive](docs/src/archive/talos-k8s.md) — the retired home Talos cluster
- [TunaOS AWS cluster handbook](docs/src/servers/aws-k8s/cluster.md) — archived cluster history
- [Adding a new machine](docs/src/onboarding.md)
- [Roles reference](docs/src/roles/)
- [Bitwarden vault setup](docs/src/bitwarden.md)

The playbook publishes `secrets_available` after the Bitwarden role verifies
that the local vault is unlocked. Secret-consuming roles use that fact as
their common gate; a locked or unavailable vault leaves existing credentials
untouched.
