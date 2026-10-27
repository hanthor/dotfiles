# Historical Talos Kubernetes Cluster

> **Historical reference, not a current deployment.** Bihar was recently online
> but is currently unreachable; its OS and services are unverified. Karnataka is
> running `projectbluefin/utah:testing`, with `multi-user.target` as its default.
> Retain `talos-k8s/`, cluster configs and Bitwarden
> notes as recovery material, not proof either machine still runs Talos.
>
> **Do not run historical reinstall, configuration or workload commands against
> repurposed nodes.** They can destroy data or change current systems. Kubernetes
> service URLs in the handbook are historical, not running endpoints.

The former two-node Talos Linux cluster was managed from `talos-k8s/`. The
[AWS Talos cluster](servers/aws-k8s/cluster.md) was terminated on 2026-10-25.

## Historical hardware roles

| Node | Role | Hardware |
|------|------|----------|
| bihar | Control plane | Intel (bare metal) |
| karnataka | Worker | AMD Strix Halo APU (GPU-enabled) |

## Historical software stack

| Component | Version | Notes |
|-----------|---------|-------|
| Talos Linux | v1.13.2 | Immutable, API-driven OS |
| Kubernetes | v1.36.1 | Via Talos |
| CNI | [flannel](https://github.com/flannel-io/flannel) | Simple overlay network |
| Tailscale Operator | — | Ingress via `*.manatee-basking.ts.net` |
| [KubeVirt](https://kubevirt.io/) | v1.8.2 | VM workloads on K8s |

## Directory structure

```
talos-k8s/
├── ai/              lemonade
├── appflowy/        appflowy cloud (Helm)
├── authentik/       sso (Helm)
├── forgejo/         git + ci/cd
├── hive/            ai agent swarm
├── homepage/        cluster landing page
├── infrastructure/  kubevirt + corral
├── longhorn/        storage
├── monitoring/      prometheus + grafana + metrics-server
├── n8n/             workflow automation
├── networking/      tailscale configs
└── testing-lab/     ci/cd test infra
```

## Former workloads

### Lemonade

[Lemonade](https://lemonade-sdk.github.io/) was an AMD-optimized local AI runtime providing omni-modal endpoints (chat, vision, image gen, speech, transcription) on karnataka's integrated AMD GPU (`amdgpu` driver baked into the Talos image via [Image Factory](https://www.talos.dev/latest/talos-guides/install/boot-assets/)). Its current operation is not established by this historical manifest.

Manifest: `talos-k8s/ai/lemonade.yaml`

### Additional services

See the [cluster handbook](servers/talos-k8s/cluster.md) for the full list — Forgejo, Hive, Authentik, n8n, AppFlowy Cloud, Grafana, Corral, and more.

## Historical cluster access

These commands apply only to a deliberately restored cluster; the retained configs do not prove a cluster is reachable.

```bash
# kubectl (from kubeconfig in Bitwarden)
kubectl get nodes

# Talos CLI (former LAN endpoints; routing is not established now)
talosctl -n <bihar-ip> version       # bihar
talosctl -n <karnataka-ip> version   # karnataka
```

## Image Factory

Karnataka's former Talos installation used a custom Image Factory image including the `siderolabs/amdgpu` system extension for GPU passthrough to containers.

## Handbook

Full cluster documentation at [`docs/src/servers/talos-k8s/cluster.md`](servers/talos-k8s/cluster.md) (hardware details, reinstall procedure, troubleshooting).
