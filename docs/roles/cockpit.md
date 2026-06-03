# cockpit

**Tags:** `services`, `cockpit`  
**Secrets needed:** No  
**Runs on:** Desktops and servers

Deploys Cockpit for web-based system management.

## What It Does

1. Creates TLS certificate directory
2. Deploys Tailscale TLS certificates for Cockpit
3. Configures Cockpit to use the Tailscale domain

## Access

Cockpit is proxied through Caddy at `https://<host>.manatee-basking.ts.net/cockpit`.

## Notes

- Skip with `skip_cockpit: true`
- Cockpit provides: terminal access, service management, storage monitoring, network config
