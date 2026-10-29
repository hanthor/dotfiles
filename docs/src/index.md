# Dotfiles Fleet Handbook

Native-unit dotfiles and infrastructure for a personal fleet. Three distinct concerns live here:

1. **Workstation config** — shells, packages, browser, SSH, Tailscale, kubeconfig, GNOME, and more
2. **Home Talos history** — retained manifests and recovery material for the former Bihar + Karnataka cluster
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

Other hosts and historical infrastructure:

- **Bihar** was recently online but is currently unreachable; its OS and services are unverified.
- **Karnataka** runs `projectbluefin/utah:testing`, defaults to `multi-user.target`,
  and is listed in the server inventory.
- The [home Talos handbook](servers/talos-k8s/cluster.md), manifests, configs and
  Bitwarden notes are historical recovery material, not proof of current state.
- The [AWS Talos cluster](servers/aws-k8s/cluster.md) was terminated on 2026-10-25; its handbook is historical.

[Spindle](servers/spindle-vps/README.md) is an OCI Frankfurt VPS running Matrix,
standalone LiveKit, School, Reef and Hub. It is not currently listed in `inventory.yml`.

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
