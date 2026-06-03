# Bihar

Kubernetes control plane + home server. [Talos Linux](https://www.talos.dev/) node.

## Hardware

- Arch: x86_64 (Intel)
- Motherboard: ASRock (MAC `A8:A1:59:E1:6D:84`)
- LAN IP: `192.168.0.5`
- Role: Control plane (Talos K8s)
- Tailscale IP: `100.85.9.86`

## OS

[Talos Linux](https://www.talos.dev/) v1.13.2 ([Kubernetes](https://kubernetes.io/) v1.36.1)

## Services

| Service | URL |
|---------|-----|
| [Cockpit](https://cockpit-project.org/) | `bihar.manatee-basking.ts.net/cockpit` |
| [Grafana](https://grafana.com/) | `bihar.manatee-basking.ts.net/grafana` |
| [Prometheus](https://prometheus.io/) | `bihar.manatee-basking.ts.net:9091` |
| Alertmanager | `bihar.manatee-basking.ts.net:9093` |
| [Authentik](https://goauthentik.io/) SSO | `bihar.manatee-basking.ts.net/auth` |
| [n8n](https://n8n.io/) | `bihar.manatee-basking.ts.net/n8n` |
| [AppFlowy](https://appflowy.io/) | `bihar.manatee-basking.ts.net/appflowy` |
| [Lima](https://github.com/lima-vm/lima) VM | `bihar.manatee-basking.ts.net/lima` |

## Networking

- Advertises subnet routes: `192.168.0.0/24`
- Tailscale DNS: disabled (uses systemd-resolved directly)
- Operator: `james`

## See also

- [Talos cluster handbook](../cluster.md)
