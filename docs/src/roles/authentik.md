# authentik

**Tags:** `services`, `identity`, `sso`  
**Secrets needed:** No  
**Runs on:** bihar only

Deploys [Authentik](https://goauthentik.io/) SSO (single sign-on) identity provider using Podman Quadlets.

## What It Does

1. Creates Quadlet config directory
2. Deploys Authentik services as Quadlet containers:
   - **PostgreSQL** — database (`authentik-db`)
   - **Redis** — cache and message broker
   - **Authentik Server** — web UI and API
   - **Authentik Worker** — background task processing
3. Creates persistent volumes for database, media, certificates, and custom templates
4. Creates a shared network (`authentik.network`)
5. Starts all services via systemd

## Access

Proxied through Caddy at `https://bihar.manatee-basking.ts.net/auth`.

## Notes

- Provides SSO for all internal services (AppFlowy, Grafana, etc.)
- Uses Podman Quadlets — no docker-compose needed
- All services run rootless as the user
