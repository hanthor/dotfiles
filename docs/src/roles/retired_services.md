# retired_services

**Tags:** `system`, `retired_services`  
**Secrets needed:** No  
**Runs on:** every systemd host except the `vps` group and Termux (`site.yml` gates on `vps` membership, `is_termux` and `service_mgr`)

Deleting a role from the repo stops the fleet from *deploying* its services, but
nothing ever removed what it had already installed — so retired podman quadlets
(Prometheus, Grafana, Cockpit, …) kept running on laptops long after their roles
were gone ([#170](https://github.com/hanthor/dotfiles/issues/170)). This role
removes those leftover unit files.

## What It Does

For every unit file in its lists that exists on the machine:

1. stops the service generated from it — quadlet service names are the file stem
   (`foo.container` → `foo.service`, `foo.volume` → `foo-volume.service`,
   `foo.network` → `foo-network.service`); plain `.service`/`.timer` files are
   also disabled
2. deletes the unit file
3. runs one `daemon-reload` (system and/or user, whichever scope had leftovers)

On a machine with none of the files, everything after one `find` over the unit
directories is skipped — the role reports no changes.

**Only unit files are removed.** Podman volumes (the data of Prometheus,
Grafana, NetBox's Postgres, …), images, and config directories such as
`/etc/cockpit`, `/etc/homepage`, `/etc/netbox` and `~/.config/monitoring` are
left alone; delete them by hand once you're sure nothing is wanted
(`podman volume ls`, `sudo podman volume ls`).

## Units

| Role | Removed in | Scope | Unit files |
|---|---|---|---|
| `cockpit` | `2af694a` | system (`/etc/containers/systemd/`) | `cockpit.container` |
| `homepage` | `f0143a6` | system | `homepage.container` |
| `netbox` | `7f3c122` | system | `netbox.container`, `netbox-worker.container`, `netbox-redis.container`, `netbox-postgres.container`, `netbox-postgres.volume`, `netbox-media.volume`, `netbox.network` |
| `netbox_agent` | `7f3c122` | system (`/etc/systemd/system/`) | `netbox-agent.timer`, `netbox-agent.service` |
| `lima` | `f0143a6` | user (`~/.config/containers/systemd/`) | `lima-bootc.container` |
| `monitoring` | `8c9b171` | user | `node-exporter`, `podman-exporter`, `alloy`, `promtail`, `prometheus` (also the hub variant), `perses`, `grafana`, `loki`, `alertmanager`, `pve-exporter`, `matrix-notifier` `.container`; `alloy-data`, `prometheus-data`, `perses-data`, `grafana-data`, `loki-data`, `alertmanager-data` `.volume`; `monitoring.network` |
| `appflowy` | `f7f2a2a` | user | `appflowy-cloud`, `appflowy-gotrue`, `appflowy-s3`, `appflowy-minio`, `appflowy-redis`, `appflowy-db` `.container`; `appflowy-s3-data`, `appflowy-minio-data`, `appflowy-db-data` `.volume`; `appflowy.network` |
| `authentik` | `f7f2a2a` | user | `authentik-server`, `authentik-worker`, `authentik-redis`, `authentik-db` `.container`; `authentik-db-data`, `authentik-media`, `authentik-certs`, `authentik-custom-templates` `.volume`; `authentik.network` |
| `n8n` | `f7f2a2a` | user | `n8n-server`, `n8n-db` `.container`; `n8n-data`, `n8n-db-data` `.volume`; `n8n.network` |

`caddy.container` is not on the list — the [`proxy`](proxy.md) role still deploys it.

## Variables

| Variable | Purpose |
|---|---|
| `retired_services_system_units` | Absolute paths of rootful quadlets / system units to remove |
| `retired_services_user_units` | File names under `~/.config/containers/systemd/` to remove |

## Notes

- When you delete a role that installed units, add them here in the same PR.
- User-scope `systemctl` gets `XDG_RUNTIME_DIR=/run/user/<uid>` pinned so it
  works from shells that don't export it.
- No `skip_` flag — the role is a no-op wherever the files are absent.
