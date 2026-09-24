# Telengana

> **Retired 2026-08-27.** Its workloads — including the tuna-os Hive, which ran
> on a local k3s here — were migrated to the
> [AWS Talos cluster](../../servers/aws-k8s/cluster.md); the Hive's operator
> timers moved to the [`hive_ops`](../../roles/hive_ops.md) role on himachal.
> The page below is historical.

Former VPS node in the fleet (`vps` group in `inventory.yml`).

## What it ran

- Ubuntu 24.04 LTS, x86_64
- A single-node k3s hosting the tuna-os Hive
- Managed by the fleet playbook (daily cron apply, no secrets/homebrew)

## Lessons carried forward

The box drifted from the fleet's hardening baseline (host firewall and
fail2ban were never enabled, and Tailscale had been logged out, leaving admin
access on the public interface). The replacement cluster keeps its admin APIs
behind an allowlisted security group, and fleet servers use the
[`server_hardening`](../../roles/server_hardening.md) role.
