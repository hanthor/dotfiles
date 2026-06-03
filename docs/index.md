# Dotfiles Fleet Handbook

Ansible-driven dotfiles and infrastructure for a personal fleet. Two distinct concerns live here:

1. **Workstation config** — shells, packages, browser, SSH, Tailscale, kubeconfig, GNOME, and more
2. **Talos K8s cluster** — manifests for the Bihar + Karnataka cluster

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

| Machine | Group | Type | Role |
|---------|-------|------|------|
| karnataka | desktop, llm | Workstation | GPU dev, K8s worker |
| himachal | desktop | Laptop | Portable workstation |
| kanpur | desktop | Laptop | Portable workstation |
| kerala | desktop | Mobile | PostMarketOS ARM device |
| dilli | desktop | Desktop | Secondary workstation |
| bihar | server | Server | Home server (Proxmox, K8s control plane) |
| vm | server | VM | Local dev VM |
| goa | server | Server | ARM server |
| matrix | vps | VPS | Public services |
| lkofoss | vps | VPS | Public services |

## Playbook Phases

The playbook runs in tagged phases:

| Phase | Tags | What |
|-------|------|------|
| 1 — System | `system` | SSH, sudo, APK packages |
| 2 — Packages | `packages` | Homebrew, Flatpak |
| 3 — Dotfiles | `dotfiles` | Shell, PI, git, neovim |
| 4 — Secrets | `secrets` | Bitwarden, SSH keys, GitHub, Tailscale, kubeconfig |
| 5 — Desktop | `desktop` | GNOME, browser, fonts, wallpaper, Easy Effects |
| 6 — Services | `services` | Systemd timers, Caddy proxy, homepage, monitoring |

Phases 4+ require Bitwarden session credentials.
