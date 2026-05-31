# Bihar

Kubernetes control plane + home server. Talos Linux node.

## Hardware

- Arch: x86_64 (Intel)
- Motherboard: ASRock (MAC `A8:A1:59:E1:6D:84`)
- LAN IP: `192.168.0.5`
- Role: Control plane (Talos K8s)
- Tailscale IP: `100.85.9.86`

## OS

Talos Linux v1.13.2 (K8s v1.36.1)

## Services

| Service | URL |
|---------|-----|
| Cockpit | `bihar.manatee-basking.ts.net/cockpit` |
| Grafana | `bihar.manatee-basking.ts.net/grafana` |
| Prometheus | `bihar.manatee-basking.ts.net:9091` |
| Alertmanager | `bihar.manatee-basking.ts.net:9093` |
| Authentik SSO | `bihar.manatee-basking.ts.net/auth` |
| n8n | `bihar.manatee-basking.ts.net/n8n` |
| AppFlowy | `bihar.manatee-basking.ts.net/appflowy` |
| Lima VM | `bihar.manatee-basking.ts.net/lima` |

## Networking

- Advertises subnet routes: `192.168.0.0/24`
- Tailscale DNS: disabled (uses systemd-resolved directly)
- Operator: `james`

## See also

- [Talos cluster handbook](../cluster.md)
