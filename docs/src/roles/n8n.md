# n8n

**Tags:** `services`, `automation`  
**Secrets needed:** No  
**Runs on:** bihar only

Deploys [n8n](https://n8n.io/) workflow automation platform using Podman Quadlets.

## What It Does

1. Creates Quadlet config directory
2. Deploys n8n as a Quadlet container
3. Starts the service via systemd

## Access

Proxied through Caddy at `https://bihar.manatee-basking.ts.net/n8n`.

## Notes

- n8n provides visual workflow automation (similar to Zapier/IFTTT, but self-hosted)
- Runs rootless as the user
- Workflows and credentials persist across container restarts
