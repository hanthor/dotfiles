# Matrix

VPS node in the hanthor fleet.

## Connection

- Hostname: `matrix.reilly.asia`
- Tailscale IP: `100.73.19.81`
- Public IP: `37.27.84.201`
- Arch: x86_64
- Auth: himachal's fleet key

## Specs

- OS: [Ubuntu 24.04.4 LTS](https://releases.ubuntu.com/noble/)
- RAM: 7.5 GiB
- Disk: 75 GB (64% used — 46G/75G)
- Uptime: typically days

## Services

| Port | Service | Exposure |
|------|---------|----------|
| 22 | SSH | Tailscale only |
| 25 | SMTP | Tailscale |
| 6443 | k8s API | Tailscale |
| 5432 | [PostgreSQL](https://www.postgresql.org/) | 🚨 Public IP exposed |
| 10248-10259 | kubelet/containerd | localhost |

## Security

- ✅ SSH: no root login, no password auth
- ✅ [fail2ban](https://github.com/fail2ban/fail2ban): active
- ✅ [UFW](https://help.ubuntu.com/community/UFW): active
- ✅ `unattended-upgrades`: active
- ✅ [Tailscale](https://tailscale.com/): running (`reilly-asia-matrix`)
- 🚨 PostgreSQL on `37.27.84.201:5432` — should be firewalled to Tailscale IPs only

## Notes

- Runs [Kubernetes](https://kubernetes.io/) (kubelet + containerd ports)
- `reilly.asia` DNS hosted on [Cloudflare](https://www.cloudflare.com/), not served from this VPS
- Fleet keys deployed: bihar, dilli, goa, himachal, kanpur, karnataka, termux
- Cron: daily playbook at 3am (no secrets/homebrew)

## Recommendations

- ⚠️ **NTP not synced** — time drift affects TLS, K8s certs
- 🔧 **Enable swap** — 7.5G RAM with no swap is risky for K8s
- 🔧 **Kernel livepatch** — `sudo pro attach` ([Ubuntu Pro](https://ubuntu.com/pro), free for personal)
- 🔧 **SSH rate limiting** — protect against brute force despite fail2ban
- 🔧 **logrotate/journald** — 731M logs, set `SystemMaxUse=500M` in journald.conf
