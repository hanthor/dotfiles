# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Native Bash-unit dotfiles + infra for a personal fleet (desktops, servers, VPS). Machines manage themselves locally via `just`, `scripts/run-units.sh`, mise and chezmoi. Secrets come from Bitwarden at runtime — the repo is public, no secrets in git.

Three distinct concerns live here:
1. **Workstation config** (`units/`, `home/`, `host_vars/`, `group_vars/`) — shells, packages, browser, SSH, Tailscale, kubeconfig, etc.
2. **Historical Talos K8s cluster IaC** (`talos-k8s/`) — retained home-cluster manifests and recovery reference in [`docs/src/servers/talos-k8s/cluster.md`](docs/src/servers/talos-k8s/cluster.md).
3. **TunaOS AWS account IaC** (`aws/`, OpenTofu) — the account is **TunaOS infrastructure**, not the personal fleet: punjab's instance, backups (S3), IAM, budgets, and (terminated, still in the code) the AWS Talos cluster's VPC/nodes/EIPs. Credits are exhausted: everything left here costs real money. Handbook: [`docs/src/servers/aws/README.md`](docs/src/servers/aws/README.md).

### Cluster recovery and current hosts

- **Home:** Karnataka runs `ghcr.io/projectbluefin/utah:testing` with `multi-user.target` as its default and a single-node K3s `v1.36.5+k3s1` server bound to its tailnet address `100.66.158.127`. KubeVirt `v1.9.1`, CDI and Corral are installed; `corral-vms/punjab` is now the active Punjab replacement, reached as `ubuntu@100.103.187.46` (tailnet name `punjab`). Reboot persistence, broker access and native no-secrets apply passed at cutover. Bihar's OS and services are unverified. Retain the former home cluster's `~/.kube/config`, `~/.talos/config`, Bitwarden notes and `talos-k8s/` manifests as recovery material; don't operate historical recovery commands on these machines.
- **AWS** (`eu-north-1`, built 2026-08-27) — **terminated 2026-10-25** after credits were exhausted. It previously ran Matrix, the Hives and the CFP dashboard. The S3 bucket `hanthor-fleet-backups-*` and the himachal-1 mirror (`~/backups/tunaos-aws-2026-10-25`) were retained; verify individual AWS resources rather than assuming they are gone. OpenTofu still describes the old cluster and can propose recreating resources.
  Configs retained as recovery material: `~/.kube/config-aws-migration`, `~/.talos/config-aws-migration`.
  Handbook: [`docs/src/servers/aws-k8s/cluster.md`](docs/src/servers/aws-k8s/cluster.md).
- **Spindle VPS** — Matrix, standalone LiveKit, School, Reef and Hub run on an Oracle Always Free A1 VM in `eu-frankfurt-1`, 2 OCPU / 12 GB, joined to the tailnet and locked down. The kit and runbook are in [`docs/src/servers/spindle-vps/`](docs/src/servers/spindle-vps/README.md); Oracle API key/config are in Bitwarden. Cloudflare DNS failover is manual, not automatic.

The former AWS Talos nodes are not in `inventory.yml`. Karnataka is an SSH-managed Utah fleet host, not a current Talos node.

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

## Historical home Talos cluster

The former Bihar control plane and Karnataka worker ran Talos `v1.13.2`, Kubernetes `v1.36.1`, Lemonade and KubeVirt. This is historical architecture, not current workload status. The [cluster handbook](docs/src/servers/talos-k8s/cluster.md) preserves recovery instructions and warns against applying them to repurposed nodes.

## TunaOS AWS account (`aws/`)

- **punjab** is now a Karnataka-hosted VM. Its former EC2 `t3.large` in `us-east-1` was stopped on 2026-10-28 and its EIP released; its root volume and recovery snapshots remain. The former Talos cluster in `eu-north-1` is terminated. The separate `runs-on` CloudFormation stack in `us-east-2` reached `DELETE_COMPLETE`; its two S3 buckets and object versions were retained.
- **Do not blindly apply `aws/`:** its configuration still describes the terminated cluster and may propose recreating paid infrastructure. Inspect live resources and review plans before changes; credits are exhausted.
- State is in S3 (`hanthor-fleet-backups-*/tofu/aws/`) and contains Talos PKI. `aws/terraform.tfvars` is gitignored and lives in Bitwarden note `aws-tofu-tfvars` (`just aws-tfvars` / `just aws-seed-tfvars`).
- Do not restart EC2 Punjab or recreate retired runners without an explicit recovery decision. Preserve the retained root volume, snapshots and S3 backups; storage still incurs charges. The root-only cutover receipt on the replacement is `/srv/punjab-migration/aws-cutover-receipt.json`; the successful shutdown service journal records EC2 stopped and EIP released.
- The former cluster uploaded Postgres dumps to `s3://hanthor-fleet-backups-*/postgres/`; the `postgres-backup-writer` key is in Bitwarden, never in tofu state.
- `prevent_destroy` in configuration does not prevent creation of resources missing from the account. Never put Talos `user_data` in the config.

## Automation (bots + Hive)

Renovate and the Hive (hive.reilly.asia, `hanthor-hive-agent`) open PRs; master is protected (CI + code-owner review, admin bypass). `.github/CODEOWNERS` is deny-by-default with carve-outs for paths that never run on the fleet (docs, tests, talos-k8s, pi skills, dep manifests) — only those auto-merge. See [`docs/src/automation.md`](docs/src/automation.md). Don't widen the carve-outs to anything the fleet timer executes.

## Don'ts

- **Don't commit `talosconfig`, `controlplane.yaml`, `worker.yaml`, or `~/.kube/config`.** `talos-k8s/.gitignore` covers the first three; the kubeconfig isn't in the repo path at all.
- **Don't reintroduce NetBox.** LAN inventory comes from `just inventory`.
- **Don't add files to `karnataka/`** — that directory was deleted in cleanup. Workstation-specific config goes in `host_vars/karnataka.yml`; `talos-k8s/` retains historical cluster manifests, not instructions to apply them to the current K3s server.
- **Don't rely on host sudo in automated/pi sessions** — `sudo -v` doesn't carry over across TTYs.
- **This repo is public.** Secrets flow through Bitwarden only — never hardcode credentials.
- **Don't commit tofu state, plans or `aws/terraform.tfvars`.** `aws/.gitignore` covers them.

## References

- [`docs/src/servers/talos-k8s/cluster.md`](docs/src/servers/talos-k8s/cluster.md) — Talos cluster handbook
- [`docs/src/roles/`](docs/src/roles/) — component references
- [`docs/src/bitwarden.md`](docs/src/bitwarden.md) — BW vault structure
- `Justfile` — every task recipe; `just --list` for a menu
- `inventory.yml`, `scripts/run-units.sh`, `mise.toml` — fleet inventory and unit entrypoints
