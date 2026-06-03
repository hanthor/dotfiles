# tailscale

**Tags:** `secrets`, `tailscale`  
**Secrets needed:** Yes  
**Runs on:** All machines

Installs and configures Tailscale mesh networking.

## What It Does

1. Installs [Tailscale](https://tailscale.com/) (if not already present)
2. Fetches the reusable auth key from Bitwarden (`tailscale-authkey`)
3. Joins the [Tailscale](https://tailscale.com/) network if not already connected
4. Configures [systemd-resolved](https://www.freedesktop.org/software/systemd/man/latest/systemd-resolved.service.html) to work with Tailscale MagicDNS

## Notes

- All fleet machines are on the `manatee-basking.ts.net` tailnet
- MagicDNS provides `*.manatee-basking.ts.net` names for every machine
- The auth key is reusable — new machines join without re-authentication
