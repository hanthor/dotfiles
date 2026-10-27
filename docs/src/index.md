# Dotfiles Fleet Handbook

Native-unit dotfiles and infrastructure for a personal fleet. Three distinct concerns live here:

1. **Workstation config** — shells, packages, browser, SSH, Tailscale, kubeconfig, GNOME, and more
2. **Home Talos K8s cluster** — manifests for the Bihar + Karnataka cluster
3. **TunaOS AWS infrastructure** — OpenTofu for the AWS account, its Talos cluster, and hosted fleet services

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

# Request native inspection (coverage is subject to integration verification)
just check

# Lint YAML and native unit shell scripts
just lint
```

## Machine Fleet

Fleet hosts, from `inventory.yml`:

| Machine | Group | Type | Role |
|---------|-------|------|------|
| kanpur | desktop | Laptop | Portable workstation |
| himachal | desktop | Laptop | Portable workstation |
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

Not managed by fleet units (Talos — `talosctl`/`kubectl` only):

- **bihar** (control plane) + **karnataka** (worker, AMD GPU) — the home cluster.
  Powered down and in storage, expected back. See the [cluster handbook](servers/talos-k8s/cluster.md).
- The [AWS Talos cluster](servers/aws-k8s/cluster.md) — Matrix/ESS, the Hive, CFP dashboard.

The `llm` group is dormant (commented out in `inventory.yml`).

## Native units

`just apply*` runs the [native units](units.md) via `scripts/run-units.sh`.
Prerequisites run in stages; independent units can run concurrently via mise,
with a sequential fallback. `just apply-tags <tag>` selects units from the
wrapper's tag map, while `just apply-nosecrets` disables unit vault access.
Unit-specific platform, profile and privilege gates still apply.

The retired `matrix` and `telengana` VPSes remain powered on for burn-in.
The shared unit library skips them; **nothing on either host may be restarted**.
See the [cutover runbook](../matrix-cutover-runbook.md).
