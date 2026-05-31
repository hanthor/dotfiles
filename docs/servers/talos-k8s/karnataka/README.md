# Karnataka

Kubernetes worker node with AMD GPU. Talos Linux node.

## Hardware

- Arch: x86_64
- CPU: AMD Strix Halo APU
- GPU: AMD integrated (exposed via KubeVirt Image Factory schematic with `siderolabs/amdgpu`)
- Role: Worker (Talos K8s)
- Tailscale IP: via MagicDNS

## OS

Talos Linux v1.13.2 (K8s v1.36.1)

## Services

| Service | URL |
|---------|-----|
| Cockpit | `karnataka.manatee-basking.ts.net/cockpit` |
| RamaLama (LLM) | `karnataka.manatee-basking.ts.net:8174` |
| BuildStream Dashboard | `karnataka.manatee-basking.ts.net/bst/` |

## K8s Workloads

- **Qwen3-27B** — vLLM serving on iGPU
- **KubeVirt v1.8.2** — VM workloads
- **Tailscale Operator** — Ingress to `*.manatee-basking.ts.net`

## Extra Brews

- `ublue-os/experimental-tap/rocm-smi-lib` (AMD GPU management)

## See also

- [Talos cluster handbook](../cluster.md)
