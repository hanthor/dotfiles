# Matrix

VPS node in the hanthor fleet.

## Connection

- Hostname: `matrix.reilly.asia`
- Tailscale IP: `100.73.19.81`
- Arch: x86_64
- Auth: shared fleet key (`SHA256:Sa9W11...`)

## OS

Linux (VPS)

## Services

- Hosts `reilly.asia` domain

## Notes

- Remote SSH access via Tailscale
- No desktop roles — server profile (vps group)

## To investigate

- [ ] SSH hardening: disable password auth, non-default port?
- [ ] fail2ban installed?
- [ ] unattended-upgrades enabled?
- [ ] Firewall (ufw/iptables) configured?
- [ ] Disk/memory usage
- [ ] What's actually running on it (nginx/caddy, certbot, etc)?
- [ ] Monitoring — Prometheus node_exporter?
- [ ] Run `just apply` to sync dotfiles and SSH keys
