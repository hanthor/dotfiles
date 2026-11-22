# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Ansible-driven dotfiles + infra for a personal fleet (desktops, servers, VPS). Each machine manages itself locally via `just` + `ansible-playbook`. Secrets come from Bitwarden at runtime — the repo is public, no secrets in git.

Three distinct concerns live here:
1. **Workstation config** (`roles/`, `site.yml`, `host_vars/`, `group_vars/`) — shells, packages, browser, SSH, Tailscale, kubeconfig, etc.
2. **Home servers** (`home-k3s/`, `hives/`) — bihar and karnataka run Bluefin with a separate single-node k3s each, linked by KubeStellar; the hives run on bihar with karnataka as cold standby. `talos-k8s/` is the **archived** Talos-era IaC (kept for tests/history; do not apply). Current state of every host: [`docs/src/fleet.md`](docs/src/fleet.md).
3. **TunaOS AWS account IaC** (`aws/`, OpenTofu) — the account is **TunaOS infrastructure**, not the personal fleet: punjab's instance, backups (S3), IAM, budgets, and (terminated, still in the code) the AWS Talos cluster's VPC/nodes/EIPs. Credits are exhausted: everything left here costs real money. Handbook: [`docs/src/servers/aws/README.md`](docs/src/servers/aws/README.md).

### Where things run (2026-11-18 — see [`docs/src/fleet.md`](docs/src/fleet.md))

- **bihar** — Bluefin (`utah:testing`), WiFi, `100.103.44.48`, `ssh james@bihar`. Single-node k3s + **KubeStellar hub** (ITS `its1`, WDS `wds1`). **Active hive host**: hub, hub-front, school, reef as rootful-podman compose in `/var/srv/hives` (wrapper `/var/srv/hives-host/hives`). In `inventory.yml` (`desktop`). Handbook: [`docs/src/servers/bihar.md`](docs/src/servers/bihar.md).
- **karnataka** — Bluefin, `100.66.158.127`. Single-node k3s with KubeVirt (VMs incl. **punjab**), ARC runners (`tuna-ci`), Frappe LMS, Corral, front-door; KubeStellar WEC; **hive cold standby**. Configured from the native-units branch (#348), not in `inventory.yml`. Handbook: [`docs/src/servers/karnataka.md`](docs/src/servers/karnataka.md).
- **spindle** — Oracle A1 VM in `eu-frankfurt-1` (2 OCPU, ARM): Matrix (Spindle + built-in OIDC), LiveKit, Caddy (public `92.5.82.232`, the front door for `school`/`reef`/`hub.tunaos.org`), the OMP auth broker, and the **hive failover coordinator** (lease `/var/lib/hive-failover/active`, `sudo hive-failover status|move|hold`). Kit/runbook: [`docs/src/servers/spindle-vps/`](docs/src/servers/spindle-vps/README.md); Oracle API key/config in Bitwarden. Not in `inventory.yml`.
- **punjab** — KubeVirt VM on karnataka (`corral-vms/punjab`), Ubuntu, `100.103.187.46`, user `ubuntu`. Agent box and this repo's Ansible host. The EC2 instance it replaced is `punjab-aws-retired`.
- **Hives** — hosting, failover lease and runbook: [`docs/src/servers/hives.md`](docs/src/servers/hives.md) (source in `hives/`); the hives themselves: [`docs/src/cluster/hive.md`](docs/src/cluster/hive.md). Exactly one host may run them; never start them by hand on the host the lease does not name.
- **KubeStellar / k3s** — [`docs/src/servers/home-k3s.md`](docs/src/servers/home-k3s.md). Fresh k3s on these hosts needs the firewalld rules there (cni0 → internal, pod→kubelet 10250, `k3s-pod-egress` policy).

**Retired** (history only; see the [archive](docs/src/archive/talos-k8s.md)): the home Talos cluster (same hardware, replaced by k3s), the AWS Talos cluster (`eu-north-1`, terminated 2026-10-25; configs `~/.kube/config-aws-migration` / `~/.talos/config-aws-migration` kept as recovery material; handbook [`docs/src/servers/aws-k8s/cluster.md`](docs/src/servers/aws-k8s/cluster.md)), and the Hetzner VPSes `matrix` / `telengana` (**nothing on them may be restarted** — see the [cutover runbook](docs/matrix-cutover-runbook.md)).

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
just seed-kube          # Overwrite BW notes kubeconfig/talosconfig with ~/.kube/config + ~/.talos/config (see below)
just onboard NAME TYPE  # Register a new machine in inventory.yml
just add-machine NAME   # Onboard + bootstrap an already-reachable machine via SSH
```

## Playbook structure

`site.yml` runs roles in tagged phases. Notable wiring:

- `bitwarden` resolves `BW_SESSION` (env, `/tmp/bw_session`, or interactive unlock), runs `bw sync` with a 15s timeout, and publishes a `secrets_available` host fact. All BW-using roles gate on `when: secrets_available | default(false)`.
- `kube` fetches `~/.kube/config` + `~/.talos/config` from Bitwarden — desktops only.
- `ssh_keys` round-trips per-machine ed25519 keys through Bitwarden, building cross-machine `authorized_keys`.

Roles are conditional on inventory group (`desktop`, `server`, `vps`, `test_fleet`, `termux_hosts`; `llm` is dormant/commented out) and on `skip_*` flags / `machine_profile` in `host_vars/`. See [`docs/src/roles/`](docs/src/roles/) for the full reference.

## Kubeconfig + Talos secrets

`~/.kube/config` and `~/.talos/config` contain cluster PKI — they live in **Bitwarden as secure notes** named `kubeconfig` and `talosconfig`. **Those notes hold the retired home Talos cluster's configs**; the k3s clusters' kubeconfigs are `/etc/rancher/k3s/k3s.yaml` on each host (punjab's `~/.kube/config` targets karnataka; bihar's has contexts `bihar`, `its1`, `wds1`) and have not been re-seeded — don't run `just apply-tags kube` on a host whose `~/.kube/config` you need to keep without checking first. The AWS cluster's are `kubeconfig-aws-migration` / `talosconfig-aws-migration`, written to `~/.kube/config-aws-migration` / `~/.talos/config-aws-migration`. Pull all four via `just apply-tags kube`; `just seed-kube` only seeds the two home-cluster notes.

`talos-k8s/.gitignore` excludes `controlplane.yaml`, `worker.yaml`, and `talosconfig` from git.

## Home k3s (replaces the Talos cluster)

No Talos anywhere now. Each of bihar/karnataka has its own k3s v1.36.5 bound to its tailnet IP (flannel on `tailscale0`, traefik/servicelb disabled); kits in `home-k3s/<host>/` (`install-host.sh`, `config.yaml`, `k3s.service`). bihar uses service CIDR `10.96.0.0/12` (KubeFlex requirement). karnataka's AMD GPU is exposed through `amdgpu-device-plugin.yaml`; Lemonade is scaled to 0. The [k3s handbook](docs/src/servers/home-k3s.md) covers design, firewalld and KubeStellar.

## TunaOS AWS account (`aws/`)

- **punjab** is no longer in AWS (it is a VM on karnataka); `aws/punjab.tf` describes the retired EC2 instance. The former Talos cluster in `eu-north-1` is terminated. `runs-on` (us-east-2) is its own CloudFormation stack — don't import it.
- **Do not blindly apply `aws/`:** its configuration still describes the terminated cluster and may propose recreating paid infrastructure. Inspect live resources and review plans before changes; credits are exhausted.
- State is in S3 (`hanthor-fleet-backups-*/tofu/aws/`) and contains Talos PKI. `aws/terraform.tfvars` is gitignored and lives in Bitwarden note `aws-tofu-tfvars`.
- Preserve the retired punjab EC2 instance's data and the S3 backups until an explicit cleanup decision exists.
- The former cluster uploaded Postgres dumps to `s3://hanthor-fleet-backups-*/postgres/`; the `postgres-backup-writer` key is in Bitwarden, never in tofu state.
- `prevent_destroy` in configuration does not prevent creation of resources missing from the account. Never put Talos `user_data` in the config.

## Automation (bots + Hive)

Renovate and the Hive open PRs; the live Hives run on bihar (karnataka standby): school (`hanthor-hive-agent`) and reef (`tuna-reef-hive`) cover `tuna-os/*`, and the hanthor spoke (`hive.reilly.asia`, also `hanthor-hive-agent`) covers `hanthor/*`, including this repo ([`hives/hanthor/hive.yaml`](hives/hanthor/hive.yaml); see [`docs/src/cluster/hive.md`](docs/src/cluster/hive.md)). master is protected (CI + code-owner review, admin bypass). `.github/CODEOWNERS` is deny-by-default with carve-outs for paths that never run on the fleet (docs, tests, talos-k8s, pi skills, dep manifests) — only those auto-merge. See [`docs/src/automation.md`](docs/src/automation.md). Don't widen the carve-outs to anything the fleet timer executes.

## Don'ts

- **Don't commit `talosconfig`, `controlplane.yaml`, `worker.yaml`, or `~/.kube/config`.** `talos-k8s/.gitignore` covers the first three; the kubeconfig isn't in the repo path at all.
- **Don't reintroduce NetBox.** LAN inventory comes from `just inventory`.
- **Don't add files to `karnataka/`** — that directory was deleted in cleanup. Workstation-specific config goes in `host_vars/karnataka.yml`; k3s manifests and kits go in `home-k3s/<host>/`. `talos-k8s/` is archived — don't add to it.
- **Don't rely on host sudo in automated/pi sessions** — `sudo -v` doesn't carry over across TTYs.
- **This repo is public.** Secrets flow through Bitwarden only — never hardcode credentials.
- **Don't commit tofu state, plans or `aws/terraform.tfvars`.** `aws/.gitignore` covers them.

## References

- [`docs/src/fleet.md`](docs/src/fleet.md) — every host: live, intermittent, retired
- [`docs/src/servers/hives.md`](docs/src/servers/hives.md) — hive hosting + failover runbook
- [`docs/src/servers/home-k3s.md`](docs/src/servers/home-k3s.md) — k3s + KubeStellar
- [`docs/src/archive/`](docs/src/archive/talos-k8s.md) — retired Talos cluster handbooks
- [`docs/src/roles/`](docs/src/roles/) — every Ansible role explained
- [`docs/src/bitwarden.md`](docs/src/bitwarden.md) — BW vault structure
- `Justfile` — every task recipe; `just --list` for a menu
- `ansible.cfg`, `site.yml`, `inventory.yml` — the playbook entrypoints
