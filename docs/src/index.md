# Dotfiles Fleet Handbook

Ansible-driven dotfiles and infrastructure for a personal fleet. Three distinct concerns live here:

1. **Workstation config** — shells, packages, browser, SSH, Tailscale, kubeconfig, GNOME, and more
2. **Home servers** — bihar and karnataka (Bluefin + k3s, linked by KubeStellar); the hives run on bihar with karnataka as standby. The [Talos manifests](archive/talos-k8s.md) are archived
3. **Hosted infrastructure** — OCI spindle (Matrix, public front door, hive failover coordinator) and the AWS account; the AWS Talos cluster is terminated

Current state of every host: **[Fleet status](fleet.md)**.

> **This handbook is public.** It covers architecture, decisions and runbooks.
> Never put secrets in it. Fleet addresses live in inventory or come from
> `just inventory`; service runbooks may document public endpoints.

## Quick Start

```bash
# Apply to local machine (most common)
just apply

# Apply specific tags only
just apply-tags kube,shell

# Apply to a remote machine
just apply-remote himachal

# Dry-run to see what would change
just check

# Lint all YAML and Ansible
just lint
```

## Machine Fleet

Ansible-managed hosts, from `inventory.yml`:

| Machine | Group | Type | Role |
|---------|-------|------|------|
| kanpur | desktop | Laptop | Portable workstation |
| himachal | desktop | Laptop | Portable workstation; legacy `hive_ops` timers retired |
| dilli | desktop | Desktop | Secondary workstation |
| kerala | desktop | Mobile | postmarketOS ARM device |
| mumbai | desktop | VM | Debian VM on the phone, `machine_profile: cli-only` |
| punjab | server | VM | Agent box, KubeVirt VM on karnataka |
| bihar | desktop | Server | Home server: active hive host, KubeStellar hub |
| goa | server | Server | [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/) ARM server |
| vm | server | VM | Local dev VM |
| termux | termux_hosts | Phone | Raw Termux/Android layer |
| test-fleet-fedora, test-fleet-node2 | test_fleet | VM | KubeVirt test VMs (`vm-test`) |
| matrix | vps | VPS | **Retired** — see the cutover runbook |
| telengana | vps | VPS | **Retired** — see the cutover runbook |

Outside this inventory:

- **karnataka** — home k3s/KubeVirt server, configured from the native-units branch. See [Karnataka](servers/karnataka.md).
- [Spindle](servers/spindle-vps/README.md) — OCI Frankfurt VPS: Matrix, LiveKit, the Caddy front door for the hives, and the [hive failover](servers/hives.md) coordinator.
- The [AWS Talos cluster](servers/aws-k8s/cluster.md) was terminated on 2026-10-25, and the home Talos cluster was replaced by k3s ([archive](archive/talos-k8s.md)).

The `llm` group is dormant (commented out in `inventory.yml`).

## Playbook Phases

`site.yml` groups roles into four commented phases. Tags cut across them — use
`just apply-tags <tag>` to target a subset.

| Phase | Roles | Main tags |
|-------|-------|-----------|
| 1 — System + packages + dotfiles | sudo, sshd, apk_packages, homebrew, termux_packages, bitwarden, shell_fonts, shell_dotfiles, omp, hive_ops, git, neovim | `system`, `packages`, `dotfiles` |
| 2 — Secrets + auth | shell_atuin, shell_ai, ssh_keys, ssh_mesh, github, tailscale, kube, forgejo_registry | `secrets` |
| 3 — Desktop apps | flatpak, bluefin_common, gnome, zen_browser (+ browser_fxa), pipewire_audio | `desktop` |
| 4 — Services | syncthing, systemd, bst_dashboard, kirocrew, proxy, tailscale_cert, server_hardening | `services` |

Only the `secrets`-tagged work needs Bitwarden. With the vault locked (or
`--skip-tags secrets`), phases 1, 3 and 4 run normally and BW-touching tasks
skip cleanly.
