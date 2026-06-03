# appflowy

**Tags:** `services`, `appflowy`  
**Secrets needed:** No  
**Runs on:** bihar only

Deploys the AppFlowy collaboration platform using Podman Quadlets.

## What It Does

1. Creates Quadlet config directory
2. Deploys AppFlowy services as Quadlet containers:
   - **PostgreSQL** — database (`appflowy-db`)
   - **Redis** — cache and message broker
   - **MinIO** — S3-compatible object storage
   - **GoTrue** — authentication service
   - **AppFlowy Cloud** — main application server
3. Creates a shared network (`appflowy.network`)
4. Starts all services via systemd

## Access

Proxied through Caddy at `https://bihar.manatee-basking.ts.net/appflowy`.

## Notes

- Uses Podman Quadlets (systemd-generator for containers) — no docker-compose needed
- All services run rootless as the user
- Data volumes are persistent across container restarts
