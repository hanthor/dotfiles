# lkofoss

VPS node in the hanthor fleet.

## Connection

- Hostname: `lkofoss.club`
- Tailscale IP: `77.42.94.83`
- Arch: x86_64

## OS

Linux (VPS)

## Services

- Hosts `lkofoss.club` domain

## Notes

- Remote SSH access via Tailscale
- No desktop roles — server profile (vps group)

## To investigate

- [ ] SSH hardening: disable password auth, non-default port?
- [ ] fail2ban installed?
- [ ] unattended-upgrades enabled?
- [ ] Firewall (ufw/iptables) configured?
- [ ] Disk/memory usage
- [ ] What's actually running (nginx/caddy, certbot, etc)?
- [ ] BW key item — `james@lkofoss` query timed out, may not exist
- [ ] Run `just apply` to sync dotfiles and SSH keys
