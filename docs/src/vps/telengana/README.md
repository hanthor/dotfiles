# Telengana

> **Retired 2026-08-27.** The tuna-os Hive moved from this host to the former
> [AWS Talos cluster](../../servers/aws-k8s/cluster.md), terminated 2026-10-25.
> School, Reef and Hub now run on the [OCI VPS](../../servers/spindle-vps/README.md).
> Restart nothing on this retired host; the page below is historical.

Former VPS node in the fleet (`vps` group in `inventory.yml`).

## What it ran

- Ubuntu 24.04 LTS, x86_64
- A single-node k3s hosting the tuna-os Hive
- Managed by the fleet playbook (daily cron apply, no secrets/homebrew)

## Lessons carried forward

The box drifted from the fleet's hardening baseline (host firewall and
fail2ban were never enabled, and Tailscale had been logged out, leaving admin
access on the public interface). The former AWS cluster kept its admin APIs
behind an allowlisted security group, and fleet servers use the
[`server_hardening`](../../roles/server_hardening.md) role.
