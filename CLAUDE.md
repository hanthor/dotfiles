# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Ansible-driven dotfiles + infra for a personal fleet (desktops, servers, VPS). Each machine manages itself locally via `just` + `ansible-playbook`. Secrets come from Bitwarden at runtime — the repo is public, no secrets in git.

Three distinct concerns live here:
1. **Workstation config** (`roles/`, `site.yml`, `host_vars/`, `group_vars/`) — shells, packages, browser, SSH, Tailscale, kubeconfig, etc.
2. **Talos K8s cluster IaC** (`talos-k8s/`) — manifests for the Bihar + Karnataka cluster. Detailed handbook in [`docs/src/servers/talos-k8s/cluster.md`](docs/src/servers/talos-k8s/cluster.md).
3. **TunaOS AWS account IaC** (`aws/`, OpenTofu) — the account is **TunaOS infrastructure**, not the personal fleet: punjab's instance, backups (S3), IAM, budgets, and (terminated, still in the code) the AWS Talos cluster's VPC/nodes/EIPs. Credits are exhausted: everything left here costs real money. Handbook: [`docs/src/servers/aws/README.md`](docs/src/servers/aws/README.md).

### Two Talos clusters, not one

- **Home** (`bihar` + `karnataka`) — on the LAN. Configs: `~/.kube/config`, `~/.talos/config`.
  **Currently powered down and in storage; expected back.** Treat it as
  temporarily offline, not decommissioned — don't delete its configs, Bitwarden
  notes, or `talos-k8s/` manifests, and expect `just doctor`/`kubectl` against it
  to fail until it returns.
- **AWS** (`eu-north-1`, built 2026-08-27) — **terminated 2026-10-25** after credits were exhausted. It previously ran Matrix, the Hives and the CFP dashboard. The S3 bucket `hanthor-fleet-backups-*` and the himachal-1 mirror (`~/backups/tunaos-aws-2026-10-25`) were retained; verify individual AWS resources rather than assuming they are gone. OpenTofu still describes the old cluster and can propose recreating resources.
  Configs retained as recovery material: `~/.kube/config-aws-migration`, `~/.talos/config-aws-migration`.
  Handbook: [`docs/src/servers/aws-k8s/cluster.md`](docs/src/servers/aws-k8s/cluster.md).
- **Spindle VPS** — Matrix, standalone LiveKit, School, Reef and Hub run on an Oracle Always Free A1 VM in `eu-frankfurt-1`, 2 OCPU / 12 GB, joined to the tailnet and locked down. The kit and runbook are in [`docs/src/servers/spindle-vps/`](docs/src/servers/spindle-vps/README.md); Oracle API key/config are in Bitwarden. Cloudflare DNS failover is manual, not automatic.

Neither cluster's nodes are Ansible-managed — Talos has no SSH. They are not in
`inventory.yml`; access is `talosctl`/`kubectl` only.

The two Hetzner VPSes it replaced (`matrix`, `telengana`) are retired but still
powered on for burn-in. **Nothing on them may be restarted** — see the
[cutover runbook](docs/matrix-cutover-runbook.md).

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

Roles are conditional on inventory group (`desktop`, `server`, `vps`, `test_fleet`, `termux_hosts`; `llm` is dormant/commented out) and on `skip_*` flags / `machine_profile` in `host_vars/`. See [`docs/src/roles/`](docs/src/roles/) for the full reference.

## Kubeconfig + Talos secrets

`~/.kube/config` and `~/.talos/config` contain cluster PKI — they live in **Bitwarden as secure notes** named `kubeconfig` and `talosconfig` (home cluster). The AWS cluster's are `kubeconfig-aws-migration` / `talosconfig-aws-migration`, written to `~/.kube/config-aws-migration` / `~/.talos/config-aws-migration`. Pull all four via `just apply-tags kube`; `just seed-kube` only seeds the two home-cluster notes.

`talos-k8s/.gitignore` excludes `controlplane.yaml`, `worker.yaml`, and `talosconfig` from git.

## Talos cluster

Two nodes: **bihar** (control plane, Intel) and **karnataka** (worker, AMD Strix Halo APU). Talos `v1.13.2`, K8s `v1.36.1`, flannel CNI. AMD GPU exposed to Kubernetes via the Image Factory schematic.

Production workloads: Lemonade (AMD-optimized local AI), KubeVirt v1.8.2 + KubeVirt Manager, Tailscale Operator (Ingress to `*.manatee-basking.ts.net`).

**The cluster handbook is [`docs/src/servers/talos-k8s/cluster.md`](docs/src/servers/talos-k8s/cluster.md)** — hardware, network, reinstall, troubleshooting.

## TunaOS AWS account (`aws/`)

- **punjab** (this repo's AWS-hosted Ansible host) is an EC2 `t3.large` in `us-east-1`; the former Talos cluster in `eu-north-1` is terminated. `runs-on` (us-east-2) is its own CloudFormation stack — don't import it.
- **Do not blindly apply `aws/`:** its configuration still describes the terminated cluster and may propose recreating paid infrastructure. Inspect live resources and review plans before changes; credits are exhausted.
- State is in S3 (`hanthor-fleet-backups-*/tofu/aws/`) and contains Talos PKI. `aws/terraform.tfvars` is gitignored and lives in Bitwarden note `aws-tofu-tfvars`.
- punjab uses Tailscale for access and SSM Session Manager for break-glass. Preserve its data and the S3 backups until a verified replacement and an explicit cleanup decision exist.
- The former cluster uploaded Postgres dumps to `s3://hanthor-fleet-backups-*/postgres/`; the `postgres-backup-writer` key is in Bitwarden, never in tofu state.
- `prevent_destroy` in configuration does not prevent creation of resources missing from the account. Never put Talos `user_data` in the config.

## Automation (bots + Hive)

Renovate and the Hive (hive.reilly.asia, `hanthor-hive-agent`) open PRs; master is protected (CI + code-owner review, admin bypass). `.github/CODEOWNERS` is deny-by-default with carve-outs for paths that never run on the fleet (docs, tests, talos-k8s, pi skills, dep manifests) — only those auto-merge. See [`docs/src/automation.md`](docs/src/automation.md). Don't widen the carve-outs to anything the fleet timer executes.

## Don'ts

- **Don't commit `talosconfig`, `controlplane.yaml`, `worker.yaml`, or `~/.kube/config`.** `talos-k8s/.gitignore` covers the first three; the kubeconfig isn't in the repo path at all.
- **Don't reintroduce NetBox.** LAN inventory comes from `just inventory`.
- **Don't add files to `karnataka/`** — that directory was deleted in cleanup. Workstation-specific config goes in `host_vars/karnataka.yml`; cluster manifests go in `talos-k8s/`.
- **Don't rely on host sudo in automated/pi sessions** — `sudo -v` doesn't carry over across TTYs.
- **This repo is public.** Secrets flow through Bitwarden only — never hardcode credentials.
- **Don't commit tofu state, plans or `aws/terraform.tfvars`.** `aws/.gitignore` covers them.

## References

- [`docs/src/servers/talos-k8s/cluster.md`](docs/src/servers/talos-k8s/cluster.md) — Talos cluster handbook
- [`docs/src/roles/`](docs/src/roles/) — every Ansible role explained
- [`docs/src/bitwarden.md`](docs/src/bitwarden.md) — BW vault structure
- `Justfile` — every task recipe; `just --list` for a menu
- `ansible.cfg`, `site.yml`, `inventory.yml` — the playbook entrypoints
