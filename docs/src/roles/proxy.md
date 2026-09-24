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

The Caddyfile (listening on `:9000`, fronted by `tailscale serve`) carries:
- `/service/<name>` — a redirect for each entry in the host's `web_services`
- `/bst/` — the BuildStream dashboard (on build machines)

There is no homepage at `/`.

## Notes

- Skip with `skip_proxy: true` in `host_vars`
- Caddyfile is templated per-host — each machine proxies its own services
