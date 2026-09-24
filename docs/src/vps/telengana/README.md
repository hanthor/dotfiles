# Telengana

> **Retired 2026-08-27.** Formerly `lkofoss` (renamed in the inventory). Its
> workloads — including the tuna-os Hive, which ran on a local k3s here — were
> migrated to the [AWS Talos cluster](../../servers/aws-k8s/cluster.md); the
> Hive's operator timers moved to the [`hive_ops`](../../roles/hive_ops.md) role
> on himachal. This box is kept powered on for burn-in only — **nothing on it
> may be restarted**. Everything below describes the box as it was.

VPS node in the hanthor fleet (`vps` group in `inventory.yml`).

## Connection

- Hostname: `lkofoss.club`
- Tailscale IP: `100.101.234.32`
- Arch: x86_64
- Auth: himachal's fleet key

## Specs

- OS: [Ubuntu 24.04.4 LTS](https://releases.ubuntu.com/noble/)
- RAM: 7.6 GiB
- Disk: 75 GB (40% used — 29G/75G)

## Services (as last surveyed, when still `lkofoss`)

| Port | Service | Exposure |
|------|---------|----------|
| 22 | SSH | Public (Tailscale was logged out) |
| 6443 | k8s API | Public |
| 10248-10259 | kubelet/containerd | localhost |

## Security (as last surveyed)

- ✅ `unattended-upgrades`: active
- ❌ [fail2ban](https://github.com/fail2ban/fail2ban): not installed
- ❌ [UFW](https://help.ubuntu.com/community/UFW): inactive
- Fleet keys deployed: bihar, dilli, goa, himachal, kanpur, karnataka, termux, bluefin
- Cron: daily playbook at 3am (no secrets/homebrew)

The old hardening to-do list (reboot, swap, journald limits, fail2ban, UFW) is
dropped: the box is retired and must not be rebooted or have services restarted.
