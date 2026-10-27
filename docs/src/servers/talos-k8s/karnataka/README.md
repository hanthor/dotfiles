# Karnataka

Karnataka runs `ghcr.io/projectbluefin/utah:testing`, is in the fleet's
`server` inventory group, and uses `multi-user.target` as its default. SSH is
available over Tailscale at `100.66.158.127`. No current workloads are assumed.

## Hardware

- Arch: x86_64
- System: [Framework Computer](https://frame.work/)
- CPU: [AMD Strix Halo APU](https://www.amd.com/en/products/processors/laptop/ryzen-ai-max-plus.html)
- GPU: AMD integrated
- LAN: reserved address on the home /24

## Historical configuration

Karnataka was the worker of the home Talos cluster. The [cluster handbook](../cluster.md),
Talos manifests and configs, and Bitwarden notes are retained as historical
recovery material; they do not establish its current OS or workloads.
