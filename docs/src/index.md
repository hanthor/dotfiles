# Dotfiles Fleet Handbook

Ansible-driven dotfiles and infrastructure for a personal fleet. Three distinct concerns live here:

1. **Workstation config** — shells, packages, browser, SSH, Tailscale, kubeconfig, GNOME, and more
2. **Home Talos K8s cluster** — manifests for the Bihar + Karnataka cluster
3. **Hosted infrastructure** — OCI spindle and AWS account configuration; the AWS Talos cluster is terminated

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
| punjab | server | Server | EC2 agent box in us-east-1 |
| goa | server | Server | [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/) ARM server |
| vm | server | VM | Local dev VM |
| termux | termux_hosts | Phone | Raw Termux/Android layer |
| test-fleet-fedora, test-fleet-node2 | test_fleet | VM | KubeVirt test VMs (`vm-test`) |
| matrix | vps | VPS | **Retired** — see the cutover runbook |
| telengana | vps | VPS | **Retired** — see the cutover runbook |

Not Ansible-managed (Talos — `talosctl`/`kubectl` only):

- **bihar** (control plane) + **karnataka** (worker, AMD GPU) — the home cluster.
  Powered down and in storage, expected back. See the [cluster handbook](servers/talos-k8s/cluster.md).
- The [AWS Talos cluster](servers/aws-k8s/cluster.md) was terminated on 2026-10-25; its handbook is historical.

[Spindle](servers/spindle-vps/README.md) is an OCI Frankfurt VPS running Matrix,
standalone LiveKit, School, Reef and Hub. It is not currently listed in `inventory.yml`.

The `llm` group is dormant (commented out in `inventory.yml`).

## Playbook Phases

`site.yml` groups roles into four commented phases. Tags cut across them — use
`just apply-tags <tag>` to target a subset.

| Phase | Roles | Main tags |
|-------|-------|-----------|
| 1 — System + packages + dotfiles | sudo, sshd, apk_packages, homebrew, termux_packages, bitwarden, shell_fonts, shell_dotfiles, hive_ops, git, neovim | `system`, `packages`, `dotfiles` |
| 2 — Secrets + auth | shell_atuin, shell_ai, ssh_keys, ssh_mesh, github, tailscale, kube, forgejo_registry | `secrets` |
| 3 — Desktop apps | flatpak, bluefin_common, gnome, zen_browser (+ browser_fxa), pipewire_audio | `desktop` |
| 4 — Services | syncthing, systemd, bst_dashboard, kirocrew, proxy, tailscale_cert, server_hardening | `services` |

The [`omp` unit](units.md) runs after Ansible, and can also use Bitwarden for its broker token. `just apply-nosecrets` skips the secret-tagged roles and passes `--no-secrets` to units.
