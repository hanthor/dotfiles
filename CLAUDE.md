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

- `bitwarden` resolves `BW_SESSION` (env, `/tmp/bw_session`, or interactive unlock), runs `bw sync` with a 15s timeout, and sets a `bw_unlocked` host fact. All BW-using roles gate on `when: bw_unlocked | default(false)`. The end-of-play `post_tasks` summary tells the operator whether the vault was unlocked, locked, or whether `--skip-tags secrets` was used.
- `kube` (new) fetches `~/.kube/config` + `~/.talos/config` from Bitwarden — desktops only.
- `ssh_keys` round-trips per-machine ed25519 keys through Bitwarden, building cross-machine `authorized_keys`.
- `homepage` builds per-host dashboards from `web_services` + `global_services` in vars.

Roles are conditional on inventory group (`desktop`, `server`, `vps`, `llm`) and on `skip_*` flags in `host_vars/`. See [`docs/roles.md`](docs/roles.md) for the full reference.

## Inventory groups

```yaml
desktop: karnataka, kerala, himachal, dilli, goa, kanpur, doctor-fleet  # shell + GNOME
server:  bihar, vm                                                       # home services
vps:     matrix, lkofoss                                                 # remote, no desktop
llm:     karnataka                                                       # GPU host, K8s worker
```

## Kubeconfig + Talos secrets

`~/.kube/config` and `~/.talos/config` both contain cluster PKI material — they live in **Bitwarden as secure notes** named `kubeconfig` and `talosconfig`.

- **Seed Bitwarden** from a machine that already has working configs: `just seed-kube`
- **Pull onto another machine**: `just apply-tags kube` (or part of `just apply`)
- **The role** is `roles/kube/`. It writes files with mode 0600 to `~/.kube/config` and `~/.talos/config`. Missing items produce a warning, not a failure.

`talos-k8s/.gitignore` excludes `controlplane.yaml`, `worker.yaml`, and `talosconfig` from git for the same reason — these contain the cluster's machine token and bootstrap secrets.

## Talos cluster

Two nodes: **bihar** (control plane, Intel) and **karnataka** (worker, AMD Strix Halo APU). Talos `v1.13.2`, K8s `v1.36.1`, flannel CNI. AMD GPU is exposed to Kubernetes via the Image Factory schematic that bakes `siderolabs/amdgpu` into the boot image.

Production workloads (currently deployed — confirmed via `kubectl get pods -A`):
- **Lemonade** — AMD-optimized local AI runtime serving omni-modal models (chat, vision, image gen, speech, transcription) on the iGPU, manifest at [`talos-k8s/lemonade.yaml`](talos-k8s/lemonade.yaml)
- **KubeVirt v1.8.2** + **KubeVirt Manager** (web UI) — VM workloads
- **Tailscale Operator** — provides Ingress to `*.manatee-basking.ts.net` for cluster services

**The cluster handbook is [`docs/cluster.md`](docs/cluster.md)** — hardware, network, reinstall procedure, troubleshooting.

## LAN inventory — nmap, not NetBox

NetBox was removed. `just inventory [subnet]` runs `scripts/nmap-inventory.sh`, which does an `nmap -sn` and crossreferences against `tailscale status --json`. Output columns: IP, MAC, hostname, vendor, Tailscale status.

## Linting

```bash
just lint
```

Uses `yamllint` (with line-length, document-start, truthy, comments-indentation disabled) and `ansible-lint`. Both are optional — if missing the recipe just skips them.

## Adding a new machine

```bash
# Already reachable via Tailscale:
just add-machine kerala desktop

# Brand new — print bootstrap command for the user to run on it:
just onboard kerala desktop
# then on the new box:
# curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh \
#   | bash -s -- --name kerala --type desktop
```

Both update `inventory.yml`, write `host_vars/<name>.yml`, commit, and push.

## host_vars overrides

Common knobs (each defaults sane in `site.yml`):

```yaml
is_arm: false
is_laptop: true
has_homepage: true
skip_kube: true            # skip kubeconfig deploy on this machine
skip_flatpak: true
skip_bluefin: true
skip_gnome: true
skip_proxy: true
skip_homepage: true
skip_lima: true
```

## browser_fxa role

The Zen/Firefox account auto-sign-in role (called from `zen_browser`) writes `signedInUser.json` after fetching credentials from a Bitwarden item named `accounts.firefox.com`. Diagnostics were tightened — failures no longer silently kill the play; you'll see `rc / stdout / stderr` and a hint to sign in manually if needed.

Caveat: this only enables FxA sign-in, not the full Sync key bundle. After this writes the file, opening the browser once may still be required to complete the Sync handshake.

## Daily workflow

Most machines have a `dotfiles-update.timer` systemd unit that runs `just apply-nosecrets` daily. Manual:

```bash
dots               # shell alias: git pull + apply-nosecrets
dots-apply         # git pull + apply with BW unlock
just update        # same as dots-apply
```

## Don'ts

- **Don't commit `talosconfig`, `controlplane.yaml`, `worker.yaml`, or `~/.kube/config`.** `talos-k8s/.gitignore` covers the first three; the kubeconfig isn't in the repo path at all.
- **Don't add files to `karnataka/`** — that directory was deleted in the cleanup. Workstation-specific config goes in `host_vars/karnataka.yml`; cluster manifests go in `talos-k8s/`.
- **Don't reintroduce NetBox.** LAN inventory comes from `just inventory`.

## References

- [`README.md`](README.md) — short overview, machine list
- [`docs/servers/talos-k8s/cluster.md`](docs/servers/talos-k8s/cluster.md) — Talos cluster handbook (hardware, ops, reinstall)
- [`docs/roles.md`](docs/roles.md) — every Ansible role explained
- [`docs/new-machine.md`](docs/new-machine.md) — onboarding walkthrough
- [`docs/bitwarden.md`](docs/bitwarden.md) — BW vault structure
- [`talos-k8s/README.md`](talos-k8s/README.md) — terse, image-factory-focused cluster notes
- `Justfile` — every task recipe; `just --list` for a menu
- `ansible.cfg`, `site.yml`, `inventory.yml` — the playbook entrypoints

## Agent skills

### Issue tracker

GitHub Issues via the `gh` CLI on `hanthor/dotfiles`. See `docs/agents/issue-tracker.md`.

### Triage labels

Defaults: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
