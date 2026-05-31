# lkofoss

VPS node in the hanthor fleet.

## Connection

- Hostname: `lkofoss.club`
- Tailscale IP: `77.42.94.83`
- Arch: x86_64
- Auth: himachal's fleet key

## Specs

- OS: Ubuntu 24.04.4 LTS
- RAM: 7.6 GiB
- Disk: 75 GB (40% used — 29G/75G)
- Uptime: 16+ weeks (very stable)

## Services

| Port | Service | Exposure |
|------|---------|----------|
| 22 | SSH | Public (Tailscale logged out) |
| 6443 | k8s API | Public |
| 10248-10259 | kubelet/containerd | localhost |

## Security

- ✅ unattended-upgrades: active
- ❌ fail2ban: **not installed**
- ❌ UFW: **inactive** — ports exposed to public internet
- ❌ Tailscale: **logged out** — SSH and k8s API exposed on public IP
- Fleet keys deployed: bihar, dilli, goa, himachal, kanpur, karnataka, termux, bluefin

## Actions needed

1. **Install fail2ban** — `sudo apt install fail2ban`
2. **Enable UFW** — allow Tailscale IPs only: `sudo ufw allow from 100.64.0.0/10`
3. **Re-auth Tailscale** — run `just apply` to join with auth key
4. **Run playbook** — sync SSH keys, configs, monitoring
