# Bihar

Kubernetes control plane. [Talos Linux](https://www.talos.dev/) node — not in `inventory.yml`, managed with `talosctl`/`kubectl` only.

> **Powered down and in storage, expected back.** See the [cluster handbook](../cluster.md).

## Hardware

- Arch: x86_64 (Intel)
- Motherboard: ASRock
- LAN: reserved address on the home /24
- Role: Control plane (Talos K8s)
- Tailscale: `bihar` (MagicDNS)

## OS

[Talos Linux](https://www.talos.dev/) v1.13.2 ([Kubernetes](https://kubernetes.io/) v1.36.1)

## Services

Bihar no longer serves anything directly — the old per-host Caddy paths
(`bihar.manatee-basking.ts.net/grafana`, `/auth`, `/n8n`, …) predate Talos.
Cluster services are reached through the Tailscale Operator; see the
[ingress list in the cluster handbook](../cluster.md#tailscale--manatee-baskingtsnet).

## Networking

Tailscale runs as a Talos system extension, configured by
[`talos-k8s/networking/tailscale-bihar.yaml`](https://github.com/hanthor/dotfiles/blob/master/talos-k8s/networking/tailscale-bihar.yaml):

- Advertises the home LAN /24 as a subnet route
- Tailscale DNS: disabled (`TS_ACCEPT_DNS=false`)

## See also

- [Talos cluster handbook](../cluster.md)
