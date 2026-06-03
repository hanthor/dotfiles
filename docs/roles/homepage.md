# homepage

**Tags:** `services`, `homepage`  
**Secrets needed:** No  
**Runs on:** All except VPS

Deploys per-host dashboards using [Homepage](https://gethomepage.dev/) showing service links, fleet status, and monitoring.

## What It Does

1. Creates homepage config directory
2. Deploys `services.yaml` from template with:
   - **Global services** — links shown on every machine (AppFlowy, Proxmox, n8n)
   - **Per-host services** — defined in `host_vars/<name>.yml` as `web_services`
   - **Fleet section** — links to every machine's homepage
3. Deploys widget configs for monitoring and status
4. Proxied by Caddy at `https://<host>.manatee-basking.ts.net`

## Per-Host Configuration

```yaml
# host_vars/dilli.yml
web_services:
  - name: Cockpit
    href: https://dilli.manatee-basking.ts.net/cockpit
    icon: cockpit.png
    description: System management
    group: System
```

## Global Services

Defined in `group_vars/all.yml` under `global_services` — shown on every machine's dashboard.

## Fleet Section

Lists all machines with homepage instances, rendered with icons and descriptions.

## Notes

- Skip with `skip_homepage: true` or set `has_homepage: false`
- Dashboard is served by a local container, proxied through Caddy
