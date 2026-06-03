# monitoring

**Tags:** `services`, `monitoring`  
**Secrets needed:** No  
**Runs on:** bihar (monitoring hub), other hosts push metrics to bihar

Deploys the [Grafana](https://grafana.com/) + [Prometheus](https://prometheus.io/) monitoring stack on bihar, and metric exporters on other machines.

## What It Does

### On bihar (monitoring hub)

- Deploys Grafana, Prometheus, and Loki via Quadlet containers
- Configures Prometheus to scrape metrics from fleet machines
- Grafana dashboards for system health, cluster status, and service uptime

### On other machines

- Deploys Node Exporter for system metrics (CPU, memory, disk, network)
- Optionally deploys cAdvisor for container metrics

## Notes

- The monitoring hub host is configurable via `monitoring_hub_host` in group vars
- Grafana is proxied at `https://bihar.manatee-basking.ts.net/grafana`
- Skip with `skip_monitoring: true`
