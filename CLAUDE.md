# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Native Bash-unit dotfiles + infra for a personal fleet (desktops, servers, VPS). Machines manage themselves locally via `just`, `scripts/run-units.sh`, mise and chezmoi. Secrets come from Bitwarden at runtime — the repo is public, no secrets in git.

Three distinct concerns live here:
1. **Workstation config** (`units/`, `home/`, `host_vars/`, `group_vars/`) — shells, packages, browser, SSH, Tailscale, kubeconfig, etc.
2. **Talos K8s cluster IaC** (`talos-k8s/`) — manifests for the Bihar + Karnataka cluster. Detailed handbook in [`docs/src/servers/talos-k8s/cluster.md`](docs/src/servers/talos-k8s/cluster.md).
3. **TunaOS AWS account IaC** (`aws/`, OpenTofu) — the account is **TunaOS infrastructure**, not the personal fleet: the AWS Talos cluster's VPC/nodes/EIPs, punjab's instance, backups (DLM + S3), IAM, budgets. Handbook: [`docs/src/servers/aws/README.md`](docs/src/servers/aws/README.md).

### Two Talos clusters, not one

- **Home** (`bihar` + `karnataka`) — on the LAN. Configs: `~/.kube/config`, `~/.talos/config`.
  **Currently powered down and in storage; expected back.** Treat it as
  temporarily offline, not decommissioned — don't delete its configs, Bitwarden
  notes, or `talos-k8s/` manifests, and expect `just doctor`/`kubectl` against it
  to fail until it returns.
- **AWS** (`eu-north-1`, built 2026-08-27) — runs Matrix/ESS, the Hives (school.tunaos.org, reef.tunaos.org, hive.reilly.asia — all visible on hub.tunaos.org), and the CFP dashboard.
  Configs: `~/.kube/config-aws-migration`, `~/.talos/config-aws-migration`.
  Handbook: [`docs/src/servers/aws-k8s/cluster.md`](docs/src/servers/aws-k8s/cluster.md).

Neither cluster's nodes are managed by fleet units — Talos has no SSH. They are not in
`inventory.yml`; access is `talosctl`/`kubectl` only.

The two Hetzner VPSes it replaced (`matrix`, `telengana`) are retired but still
powered on for burn-in. **Nothing on them may be restarted** — see the
[cutover runbook](docs/matrix-cutover-runbook.md).
Native units' shared library skips `matrix` and `telengana` before unit work to protect these hosts; do not rely on that guard as authorization to change or restart them.

## Core commands

```bash
just apply              # Local apply with Bitwarden secrets (most common)
just apply-remote HOST  # Apply to a single remote, forwarding BW session over SSH
just apply-all          # Apply in parallel to all online Tailscale-reachable hosts
just apply-tags TAGS    # Subset apply, e.g. `just apply-tags kube,shell`
just check              # Native inspection; coverage is subject to integration verification
just lint               # YAML lint and native unit shell checks
just doctor             # Health-check local machine; `doctor-fleet` does all hosts
just inventory          # nmap LAN + Tailscale crosswalk → table of who's on
just seed-kube          # Push this machine's kubeconfig + talosconfig to Bitwarden
just onboard NAME TYPE  # Register a new machine in inventory.yml
just add-machine NAME   # Onboard + bootstrap an already-reachable machine via SSH
```

## Native configuration

`just apply*` invokes `scripts/run-units.sh`, which runs `units/` in prerequisite stages via mise, with a sequential fallback. It selects units by the wrapper's tag map and honors each unit's own platform, profile and host-variable gates. See [`docs/src/units.md`](docs/src/units.md).

- Apply recipes resolve and sync Bitwarden; unit helpers use `BW_SESSION` or `/tmp/bw_session` noninteractively, and honor `--no-secrets`.
- The `kube` unit fetches kubeconfig and talosconfig from Bitwarden on eligible desktops.
- `ssh-keys` and `ssh-mesh` handle key lifecycle and authorization. `home/` is the chezmoi source for shell, Git, Neovim and Atuin config.

Groups in `inventory.yml`, `skip_*` flags and `machine_profile` influence individual units. See [`docs/src/roles/`](docs/src/roles/) for component references.

## Kubeconfig + Talos secrets

`~/.kube/config` and `~/.talos/config` contain cluster PKI — they live in **Bitwarden as secure notes** named `kubeconfig` and `talosconfig` (home cluster). The AWS cluster's are `kubeconfig-aws-migration` / `talosconfig-aws-migration`, written to `~/.kube/config-aws-migration` / `~/.talos/config-aws-migration`. Pull all four via `just apply-tags kube`; `just seed-kube` only seeds the two home-cluster notes.

`talos-k8s/.gitignore` excludes `controlplane.yaml`, `worker.yaml`, and `talosconfig` from git.

## Talos cluster

Two nodes: **bihar** (control plane, Intel) and **karnataka** (worker, AMD Strix Halo APU). Talos `v1.13.2`, K8s `v1.36.1`, flannel CNI. AMD GPU exposed to Kubernetes via the Image Factory schematic.

Production workloads: Lemonade (AMD-optimized local AI), KubeVirt v1.8.2 + KubeVirt Manager, Tailscale Operator (Ingress to `*.manatee-basking.ts.net`).

**The cluster handbook is [`docs/src/servers/talos-k8s/cluster.md`](docs/src/servers/talos-k8s/cluster.md)** — hardware, network, reinstall, troubleshooting.

## TunaOS AWS account (`aws/`)

- **punjab** (this repo's only AWS-hosted fleet host) is an EC2 `t3.large` in `us-east-1`; the Talos cluster is in `eu-north-1`; `runs-on` (us-east-2) is its own CloudFormation stack — don't import it.
- `just aws-plan` / `just aws-apply`. A plan against the live account must read "No changes"; console edits are drift — codify or revert them.
- State is in S3 (`hanthor-fleet-backups-*/tofu/aws/`) and contains Talos PKI via node `user_data`. `aws/terraform.tfvars` (admin IPs, alert email) is gitignored and lives in Bitwarden note `aws-tofu-tfvars` (`just aws-tfvars` / `just aws-seed-tfvars`).
- punjab has **no public inbound** (SG empty): Tailscale for access, SSM Session Manager for break-glass. Its EIP is allowlisted on the cluster admin SG, so kubectl/talosctl work from it.
- Postgres dumps go off-cluster to `s3://hanthor-fleet-backups-*/postgres/` via IAM user `postgres-backup-writer` (no delete; key in BW `postgres-backup-s3` + k8s Secret, never in tofu state).
- Never put Talos `user_data` in the config — nodes `ignore_changes` it. `prevent_destroy` guards nodes, punjab, the worker EIP (DNS), pgdata and the bucket.

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
- [`docs/src/roles/`](docs/src/roles/) — component references
- [`docs/src/bitwarden.md`](docs/src/bitwarden.md) — BW vault structure
- `Justfile` — every task recipe; `just --list` for a menu
- `inventory.yml`, `scripts/run-units.sh`, `mise.toml` — fleet inventory and unit entrypoints
