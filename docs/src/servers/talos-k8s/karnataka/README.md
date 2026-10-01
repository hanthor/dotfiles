# Karnataka

Kubernetes worker node with AMD GPU. [Talos Linux](https://www.talos.dev/) node — not in `inventory.yml`, managed with `talosctl`/`kubectl` only.

> **Powered down and in storage, expected back.** See the [cluster handbook](../cluster.md).

## Hardware

- Arch: x86_64
- System: [Framework Computer](https://frame.work/)
- CPU: [AMD Strix Halo APU](https://www.amd.com/en/products/processors/laptop/ryzen-ai-max-plus.html)
- GPU: AMD integrated (exposed via [Talos Image Factory](https://www.talos.dev/latest/talos-guides/install/boot-assets/) schematic with [`siderolabs/amdgpu`](https://github.com/siderolabs/extensions/tree/main/amdgpu))
- LAN: reserved address on the home /24
- Role: Worker (Talos K8s)
- Tailscale IP: via MagicDNS

## OS

[Talos Linux](https://www.talos.dev/) v1.13.2 ([Kubernetes](https://kubernetes.io/) v1.36.1)

## K8s Workloads

- **[Lemonade](https://lemonade-sdk.github.io/)** — AMD-optimized local AI runtime ([omni-modal](https://lemonade-sdk.github.io/docs/category/endpoints): chat, vision, image gen, speech, transcription) on iGPU
- **[KubeVirt](https://kubevirt.io/) v1.8.2** — VM workloads
- **[Tailscale Operator](https://tailscale.com/kb/1236/kubernetes-operator)** — Ingress to `*.manatee-basking.ts.net`

## See also

- [Talos cluster handbook](../cluster.md)
