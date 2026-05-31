# Matrix

VPS node in the hanthor fleet.

## Connection

- Hostname: `matrix.reilly.asia`
- Tailscale IP: `100.73.19.81`
- Public IP: `37.27.84.201`
- Arch: x86_64
- Auth: himachal's fleet key

## Specs

- OS: Ubuntu 24.04.4 LTS
- RAM: 7.5 GiB
- Disk: 75 GB (64% used — 46G/75G)
- Uptime: typically days

## Services

| Port | Service | Exposure |
|------|---------|----------|
| 22 | SSH | Tailscale only |
| 25 | SMTP | Tailscale |
| 6443 | k8s API | Tailscale |
| 5432 | PostgreSQL | 🚨 Public IP exposed |
| 10248-10259 | kubelet/containerd | localhost |

## Security

- ✅ SSH: no root login, no password auth
- ✅ fail2ban: active
- ✅ UFW: active
- ✅ unattended-upgrades: active
- ✅ Tailscale: running (`reilly-asia-matrix`)
- 🚨 PostgreSQL on `37.27.84.201:5432` — should be firewalled to Tailscale IPs only

## Notes

- Runs Kubernetes (kubelet + containerd ports)
- `reilly.asia` DNS hosted on Cloudflare, not served from this VPS
- Fleet keys deployed: bihar, dilli, goa, himachal, kanpur, karnataka, termux
