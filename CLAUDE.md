# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Ansible-driven dotfiles + infra for a personal fleet (desktops, servers, VPS). Each machine manages itself locally via `just` + `ansible-playbook`. Secrets come from Bitwarden at runtime — the repo is public, no secrets in git.

Two distinct concerns live here:
1. **Workstation config** (`roles/`, `site.yml`, `host_vars/`, `group_vars/`) — shells, packages, browser, SSH, Tailscale, kubeconfig, etc.
2. **Talos K8s cluster IaC** (`talos-k8s/`) — manifests for the Bihar + Karnataka cluster. Detailed handbook in [`docs/cluster.md`](docs/cluster.md).

## Core commands

```bash
just apply              # Local apply with Bitwarden secrets (most common)
just apply-remote HOST  # Apply to a single remote, forwarding BW session over SSH
just apply-all          # Apply in parallel to all online Tailscale-reachable hosts
just apply-tags TAGS    # Subset apply, e.g. `just apply-tags kube,shell`
just check              # Dry-run
just lint               # yamllint + ansible-lint
just doctor             # Health-check local machine; `doctor-fleet` does all hosts
just inventory          # nmap LAN + Tailscale crosswalk → table of who's on
just seed-kube          # Push this machine's kubeconfig + talosconfig to Bitwarden
just onboard NAME TYPE  # Register a new machine in inventory.yml
just add-machine NAME   # Onboard + bootstrap an already-reachable machine via SSH
```

## Playbook structure

`site.yml` runs roles in tagged phases. Notable wiring:

- `bitwarden` resolves `BW_SESSION` (env, `/tmp/bw_session`, or interactive unlock), runs `bw sync` with a 15s timeout, and sets a `bw_unlocked` host fact. All BW-using roles gate on `when: bw_unlocked | default(false)`.
- `kube` fetches `~/.kube/config` + `~/.talos/config` from Bitwarden — desktops only.
- `ssh_keys` round-trips per-machine ed25519 keys through Bitwarden, building cross-machine `authorized_keys`.
- `homepage` builds per-host dashboards from `web_services` + `global_services` in vars.

Roles are conditional on inventory group (`desktop`, `server`, `vps`, `llm`) and on `skip_*` flags in `host_vars/`. See [`docs/roles.md`](docs/roles.md) for the full reference.

## Kubeconfig + Talos secrets

`~/.kube/config` and `~/.talos/config` contain cluster PKI — they live in **Bitwarden as secure notes** named `kubeconfig` and `talosconfig`. Seed via `just seed-kube`, pull via `just apply-tags kube`.

`talos-k8s/.gitignore` excludes `controlplane.yaml`, `worker.yaml`, and `talosconfig` from git.

## Talos cluster

Two nodes: **bihar** (control plane, Intel) and **karnataka** (worker, AMD Strix Halo APU). Talos `v1.13.2`, K8s `v1.36.1`, flannel CNI. AMD GPU exposed to Kubernetes via the Image Factory schematic.

Production workloads: Lemonade (AMD-optimized local AI), KubeVirt v1.8.2 + KubeVirt Manager, Tailscale Operator (Ingress to `*.manatee-basking.ts.net`).

**The cluster handbook is [`docs/cluster.md`](docs/cluster.md)** — hardware, network, reinstall, troubleshooting.

## Don'ts

- **Don't commit `talosconfig`, `controlplane.yaml`, `worker.yaml`, or `~/.kube/config`.** `talos-k8s/.gitignore` covers the first three; the kubeconfig isn't in the repo path at all.
- **Don't reintroduce NetBox.** LAN inventory comes from `just inventory`.
- **Don't add files to `karnataka/`** — that directory was deleted in cleanup. Workstation-specific config goes in `host_vars/karnataka.yml`; cluster manifests go in `talos-k8s/`.
- **Don't rely on host sudo in automated/pi sessions** — `sudo -v` doesn't carry over across TTYs.
- **This repo is public.** Secrets flow through Bitwarden only — never hardcode credentials.

## References

- [`docs/cluster.md`](docs/cluster.md) — Talos cluster handbook
- [`docs/roles.md`](docs/roles.md) — every Ansible role explained
- [`docs/bitwarden.md`](docs/bitwarden.md) — BW vault structure
- `Justfile` — every task recipe; `just --list` for a menu
- `ansible.cfg`, `site.yml`, `inventory.yml` — the playbook entrypoints

## Agent skills

### Issue tracker

GitHub Issues via the `gh` CLI on `hanthor/dotfiles`. See `docs/agents/issue-tracker.md`.

### Triage labels

Defaults: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
