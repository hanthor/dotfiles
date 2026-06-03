# tailscale_cert

**Tags:** `services`, `tailscale_cert`  
**Secrets needed:** No  
**Runs on:** All except VPS

Fetches and deploys Tailscale TLS certificates for HTTPS on `*.manatee-basking.ts.net`.

## What It Does

1. Creates certificate storage directory
2. Fetches TLS certificates from Tailscale for the machine's MagicDNS name
3. Installs certificates where Caddy and other services can use them

## Notes

- Tailscale provides free TLS certificates for nodes on your tailnet
- Certificates auto-renew — no Let's Encrypt needed for internal services
- The Caddy proxy uses these certificates for all `*.manatee-basking.ts.net` services
