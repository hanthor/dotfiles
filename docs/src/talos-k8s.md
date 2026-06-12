# Talos Kubernetes Cluster

Two-node Kubernetes cluster running on Talos Linux, managed from the `talos-k8s/` directory.

## Hardware

| Node | Role | Hardware |
|------|------|----------|
| bihar | Control plane | Intel (bare metal) |
| karnataka | Worker | AMD Strix Halo APU (GPU-enabled) |

## Software Stack

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

## Running Workloads

### Lemonade

[Lemonade](https://lemonade-sdk.github.io/) — AMD-optimized local AI runtime providing omni-modal endpoints (chat, vision, image gen, speech, transcription) on karnataka's integrated AMD GPU (`amdgpu` driver baked into the Talos image via [Image Factory](https://www.talos.dev/latest/talos-guides/install/boot-assets/)).

Manifest: `talos-k8s/ai/lemonade.yaml`

### Additional services

See the [cluster handbook](servers/talos-k8s/cluster.md) for the full list — Forgejo, Hive, Authentik, n8n, AppFlowy Cloud, Grafana, Corral, and more.

## Cluster Access

```bash
# kubectl (from kubeconfig in Bitwarden)
kubectl get nodes

# Talos CLI
talosctl -n 100.85.9.86 version
talosctl -n 100.67.142.116 version
```

## Image Factory

Karnataka uses a custom Talos image from Image Factory that includes the `siderolabs/amdgpu` system extension for GPU passthrough to containers.

## Handbook

Full cluster documentation at [`docs/src/servers/talos-k8s/cluster.md`](servers/talos-k8s/cluster.md) (hardware details, reinstall procedure, troubleshooting).
