# Talos Kubernetes Cluster

Two-node Kubernetes cluster running on Talos Linux, managed from the `talos-k8s/` directory.

## Hardware

| Node | Role | Hardware |
|------|------|----------|
| bihar | Control plane | Intel (Proxmox VM) |
| karnataka | Worker | AMD Strix Halo APU (GPU-enabled) |

## Software Stack

| Component | Version | Notes |
|-----------|---------|-------|
| Talos Linux | v1.13.2 | Immutable, API-driven OS |
| Kubernetes | v1.36.1 | Via Talos |
| CNI | [flannel](https://github.com/flannel-io/flannel) | Simple overlay network |
| Tailscale Operator | — | Ingress via `*.manatee-basking.ts.net` |
| [KubeVirt](https://kubevirt.io/) | v1.8.2 | VM workloads on K8s |

## Running Workloads

### qwen3-27b

[vLLM](https://docs.vllm.ai/) serving [Qwen3-27B](https://huggingface.co/Qwen/Qwen3-27B) on karnataka's integrated AMD GPU (`amdgpu` driver baked into the Talos image via [Image Factory](https://www.talos.dev/latest/talos-guides/install/boot-assets/)).

Manifest: `talos-k8s/qwen3-27b.yaml`

### KubeVirt

Virtual machine management on Kubernetes with KubeVirt Manager web UI.

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

Full cluster documentation at `docs/cluster.md` (hardware details, reinstall procedure, troubleshooting).
