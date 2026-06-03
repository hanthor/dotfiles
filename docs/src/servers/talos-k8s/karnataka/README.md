# Karnataka

Kubernetes worker node with AMD GPU. [Talos Linux](https://www.talos.dev/) node.

## Hardware

- Arch: x86_64
- System: [Framework Computer](https://frame.work/) (MAC `9C:BF:0D:00:E5:0F`)
- CPU: [AMD Strix Halo APU](https://www.amd.com/en/products/processors/laptop/ryzen-ai-max-plus.html)
- GPU: AMD integrated (exposed via [KubeVirt Image Factory](https://www.talos.dev/latest/talos-guides/install/boot-assets/) schematic with [`siderolabs/amdgpu`](https://github.com/siderolabs/extensions/tree/main/amdgpu))
- Role: Worker (Talos K8s)
- Tailscale IP: via MagicDNS

## OS

[Talos Linux](https://www.talos.dev/) v1.13.2 ([Kubernetes](https://kubernetes.io/) v1.36.1)

## Services

| Service | URL |
|---------|-----|
| [Cockpit](https://cockpit-project.org/) | `karnataka.manatee-basking.ts.net/cockpit` |
| RamaLama (LLM) | `karnataka.manatee-basking.ts.net:8174` |
| BuildStream Dashboard | `karnataka.manatee-basking.ts.net/bst/` |

## K8s Workloads

- **[Lemonade](https://lemonade-sdk.github.io/)** — AMD-optimized local AI runtime ([omni-modal](https://lemonade-sdk.github.io/docs/category/endpoints): chat, vision, image gen, speech, transcription) on iGPU
- **[KubeVirt](https://kubevirt.io/) v1.8.2** — VM workloads
- **[Tailscale Operator](https://tailscale.com/kb/1236/kubernetes-operator)** — Ingress to `*.manatee-basking.ts.net`

## Extra Brews

- `ublue-os/experimental-tap/rocm-smi-lib` (AMD GPU management)

## See also

- [Talos cluster handbook](../cluster.md)
