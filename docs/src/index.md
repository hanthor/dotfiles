# Dotfiles Fleet Handbook

Ansible-driven dotfiles and infrastructure for a personal fleet. Two distinct concerns live here:

1. **Workstation config** — shells, packages, browser, SSH, Tailscale, kubeconfig, GNOME, and more
2. **Talos K8s cluster** — manifests for the Bihar + Karnataka cluster

> **This handbook is public.** It covers architecture, decisions and runbooks.
> Host-specific addresses and cloud resource identifiers are deliberately left
> out — they live in the repo's inventory and IaC (`inventory.yml`,
> `host_vars/`, `aws/`), or come from `just inventory`. Runbooks use
> placeholders such as `<host>` and `<node-ip>` where you substitute them.

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
| himachal | desktop | Laptop | Portable workstation; runs `hive_ops` |
| dilli | desktop | Desktop | Secondary workstation |
| kerala | desktop | Mobile | postmarketOS ARM device |
| mumbai | desktop | VM | Debian VM on the phone, `machine_profile: cli-only` |
| punjab | server | Server | Headless Ubuntu agent box (EC2 `t3.large`, us-east-1) |
| goa | server | Server | [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/) ARM server |
| vm | server | VM | Local dev VM |
| termux | termux_hosts | Phone | Raw Termux/Android layer |
| test-fleet-fedora, test-fleet-node2 | test_fleet | VM | KubeVirt test VMs (`vm-test`) |
| matrix | vps | VPS | **Retired** — see the cutover runbook |
| telengana | vps | VPS | **Retired** — see the cutover runbook |

Not Ansible-managed (Talos — `talosctl`/`kubectl` only):

- **bihar** (control plane) + **karnataka** (worker, AMD GPU) — the home cluster.
  Powered down and in storage, expected back. See the [cluster handbook](servers/talos-k8s/cluster.md).
- The [AWS Talos cluster](servers/aws-k8s/cluster.md) — Matrix/ESS, the Hive, CFP dashboard.

The `llm` group is dormant (commented out in `inventory.yml`).

## Playbook Phases

`site.yml` groups roles into four commented phases. Tags cut across them — use
`just apply-tags <tag>` to target a subset.

| Phase | Roles | Main tags |
|-------|-------|-----------|
| 1 — System + packages + dotfiles | sudo, sshd, apk_packages, homebrew, termux_packages, bitwarden, shell_fonts, shell_dotfiles, pi, hive_ops, git, neovim | `system`, `packages`, `dotfiles` |
| 2 — Secrets + auth | shell_atuin, shell_ai, ssh_keys, ssh_mesh, github, tailscale, kube, forgejo_registry | `secrets` |
| 3 — Desktop apps | flatpak, bluefin_common, gnome, zen_browser (+ browser_fxa), pipewire_audio | `desktop` |
| 4 — Services | syncthing, systemd, bst_dashboard, proxy, tailscale_cert, server_hardening | `services` |

Only the `secrets`-tagged work needs Bitwarden. With the vault locked (or
`--skip-tags secrets`), phases 1, 3 and 4 run normally and BW-touching tasks
skip cleanly.
