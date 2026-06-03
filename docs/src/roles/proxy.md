# proxy (Caddy)

**Tags:** `services`, `proxy`, `caddy`  
**Secrets needed:** Yes (TLS certificates)  
**Runs on:** All except VPS (`skip_proxy: false`)

Deploys [Caddy](https://caddyserver.com/) as a reverse proxy with automatic TLS certificates.

## What It Does

1. Creates Caddy config directory
2. Deploys `Caddyfile` from template with per-host service routes
3. Proxies internal services to `*.manatee-basking.ts.net` subdomains
4. Uses [Tailscale](https://tailscale.com/) certificates for TLS

## Proxied Services

Caddy routes traffic for services like:
- Grafana (monitoring)
- Homepage dashboards
- Cockpit (system management)
- AppFlowy, Authentik, n8n (on bihar)
- BST Dashboard (on build machines)

## Notes

- Skip with `skip_proxy: true` in `host_vars`
- Caddyfile is templated per-host — each machine proxies its own services
