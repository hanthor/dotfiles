# Cluster Handbook — Talos Linux on Bihar + Karnataka

> **Status: powered down and in storage (as of 2026-08-27), expected back.**
> Temporarily offline, *not* decommissioned — keep its configs, Bitwarden notes
> (`kubeconfig` / `talosconfig`), and `talos-k8s/` manifests. `kubectl` and
> `just doctor` will fail against it until it returns. Workloads that needed to
> stay up (Matrix, Hive, CFP dashboard) run on the
> [AWS Talos cluster](../aws-k8s/cluster.md).
>
> **When it returns**, before applying anything under `talos-k8s/ai/`:
> run [`talos-k8s/ai/migrate-pv-path.sh`](https://github.com/hanthor/dotfiles/blob/master/talos-k8s/ai/migrate-pv-path.sh)
> first. `lemonade.yaml` already points its PVs at `/var/lib/…`, but the models
> are still under `/var/tmp/…` on karnataka. Applying the manifest first
> orphans them (#29). Then follow the prerequisites in
> [`talos-k8s/ai/README.md`](https://github.com/hanthor/dotfiles/blob/master/talos-k8s/ai/README.md)
> for the backup job and run `lemonade-warmup.sh` (#26, #27).
>
> **Home Hummingbird migration: prepared, not deployed.** The build/install and
> activation procedure is in [section 12](#12-hummingbirdbootc-migration-home-only).
> The home machines remain offline/in storage; the Talos recovery instructions
> below and all existing home/AWS credentials remain valid recovery material.


> **Two-node [Talos Linux](https://www.talos.dev/) [Kubernetes](https://kubernetes.io/) cluster.**
> AMD Strix Halo GPU acceleration · [Lemonade](https://lemonade-sdk.github.io/) · [KubeVirt](https://kubevirt.io/) · [Tailscale](https://tailscale.com/) ingress.
> Everything you need to bring this cluster back from zero.

## Table of contents

1. [Overview](#1-overview)
2. [Hardware](#2-hardware)
3. [Network](#3-network)
4. [Talos installer image (with AMD GPU)](#4-talos-installer-image-with-amd-gpu)
5. [Cluster bootstrap](#5-cluster-bootstrap)
6. [AMD GPU exposed to Kubernetes](#6-amd-gpu-exposed-to-kubernetes)
7. [Production workloads](#7-production-workloads)
8. [Tailscale operator (ingress)](#8-tailscale-operator-ingress)
9. [Day-to-day operations](#9-day-to-day-operations)
10. [Reinstall procedure](#10-reinstall-procedure)
11. [Troubleshooting](#11-troubleshooting)
12. [Hummingbird/bootc migration (home only)](#12-hummingbirdbootc-migration-home-only)

---

## 1. Overview

```
┌──────────────────────────────────────────────────────────────┐
│                       Kubernetes v1.36.1                      │
│                        (Talos v1.13.2)                        │
│                                                               │
│   ┌────────────────────────┐   ┌────────────────────────┐    │
│   │  bihar  (control plane)│   │ karnataka  (worker)    │    │
│   │  Intel CPU             │   │ AMD Ryzen AI MAX+ 395  │    │
│   │  /dev/nvme0n1          │   │ AMD Radeon 8060S iGPU  │    │
│   │                        │   │ /dev/nvme0n1           │    │
│   │  kube-apiserver        │   │ amdgpu-device-plugin   │    │
│   │  etcd / scheduler /    │   │ amdgpu-labeller        │    │
│   │  controller-manager    │   │ Lemonade               │    │
│   │  KubeVirt control      │   │ Forgejo + runner       │    │
│   │  Forgejo + runner      │   │ Hive agent swarm       │    │
│   │  ArgoCD + Argo WF      │   │ KubeVirt virt-handler  │    │
│   │  Grafana / Prometheus  │   │ Longhorn CSI           │    │
│   │  Authentik + n8n       │   │ AppFlowy Cloud         │    │
│   │  Longhorn CSI / UI     │   │ Corral VMs             │    │
│   │  KubeVirt Manager      │   │                        │    │
│   └────────────────────────┘   └────────────────────────┘    │
│                                                               │
│   CNI: flannel · kube-proxy: on · Storage: longhorn + local-path      │
│   Tailscale Operator → ts.net ingress for cluster services    │
└──────────────────────────────────────────────────────────────┘
```

The cluster is **not diskless** — Talos installs itself onto `/dev/nvme0n1` on each node and persists. Reboots survive.

**Source of truth for manifests:** [`talos-k8s/`](https://github.com/hanthor/dotfiles/tree/master/talos-k8s) in this repo.
**Source of truth for secrets** (`talosconfig`, `controlplane.yaml`, `worker.yaml`, `kubeconfig`): Bitwarden, fetched onto your workstation by the `kube` role.

---

## 2. Hardware

### Karnataka (worker)

| Component       | Detail |
|-----------------|--------|
| CPU             | AMD Ryzen AI MAX+ 395 (Strix Halo) — 16 cores / 32 threads, 5.18 GHz boost |
| RAM             | 62 GB unified memory (CPU + GPU share via UMA) |
| GPU             | AMD Radeon 8060S — RDNA 3.5 (`gfx1151`), integrated |
| NIC             | Realtek RTL8126 5GbE (`enp191s0`) |
| WiFi            | [MediaTek MT7925](https://www.mediatek.com/products/broadband-wifi/mediatek-filogic-380) Wi-Fi 7 |
| Boot disk       | Crucial P3 1TB (`/dev/nvme0n1`) |
| Secondary       | WD Black SN850X 1TB (`/dev/nvme1n1`) — **FAILING** (I/O errors). Do not use. Replace with new drive. |

### Bihar (control plane)

| Component       | Detail |
|-----------------|--------|
| CPU             | Intel x86_64 |
| Boot disk       | `/dev/nvme0n1` |

---

## 3. Network

### LAN — flat home /24

DHCP/DNS are served by the home router, which hands out fixed addresses from its address-reservation table — see [Gateway](../../network/gateway/README.md). Older revisions of this page said dnsmasq on bihar; that predates Talos, which can't run it on the host.

| Host        | Address  | Role                       |
|-------------|----------|----------------------------|
| bihar       | reserved | K8s control plane, home services |
| karnataka   | reserved | K8s worker, LLM host |
| goa         | reserved | Raspberry Pi, fleet control |
| kvm         | reserved | NanoKVM (plugged into karnataka) |

The commands below use `<bihar-ip>` / `<karnataka-ip>` for the nodes' LAN
addresses. Run `just inventory` to rescan with nmap and get the current values
(they are also the endpoints in the talosconfig).

### Internet — data-capped

The home connection has a monthly data cap; exceeding it throttles to a crawl
until the next billing cycle.

> **May 2026:** The cap was hit (largely model downloads and image pulls) and
> the link was throttled for about a week. Lesson: budget large model
> downloads and bulk image pulls against the cap. LAN traffic is unaffected.

### Tailscale — `manatee-basking.ts.net`

Cluster ingress goes through the [Tailscale Operator](https://tailscale.com/kb/1236/kubernetes-operator). Services with an `Ingress` resource targeting `tailscale` ingressClassName get a `<name>.manatee-basking.ts.net` URL automatically.

| Service             | URL |
|---------------------|-----|
| Cluster homepage    | `https://home.manatee-basking.ts.net` |
| Lemonade (AI)       | `https://lemonade.manatee-basking.ts.net/v1` |
| Hive (agent swarm)  | `https://hive.manatee-basking.ts.net` |
| Forgejo (git + CI)  | `https://forgejo.manatee-basking.ts.net` |
| ArgoCD (GitOps)     | `https://argocd.manatee-basking.ts.net` |
| Grafana (metrics)   | `https://grafana.manatee-basking.ts.net` |
| Corral (VM dashboard)| `https://corral.manatee-basking.ts.net` |
| KubeVirt Manager    | `https://kubevirt-manager.manatee-basking.ts.net` |
| Authentik (SSO)     | `https://auth.manatee-basking.ts.net` |
| n8n (workflows)     | `https://n8n.manatee-basking.ts.net` |
| AppFlowy (collab)   | `https://appflowy.manatee-basking.ts.net` |

### Kubernetes internal

| Network | CIDR |
|---------|------|
| Pod     | `10.244.0.0/16` (flannel) |
| Service | `10.96.0.0/12` |

---

## 4. Talos installer image (with AMD GPU)

Talos ships with an immutable root filesystem, so kernel modules cannot be added at runtime. The AMD GPU driver and the Longhorn iSCSI tooling are **baked into the boot image** via the [Talos Image Factory](https://factory.talos.dev).

**Schematic ID (current, 2026-06-11):** `3a33ec6dfc8cfd61d2a3db3caf97894f31e913952d71ce3c3fbbe565a3f08339`

**Extensions baked in:**
- `siderolabs/amdgpu` — AMD GPU kernel driver
- `siderolabs/iscsi-tools` — iscsid, for Longhorn block storage
- `siderolabs/util-linux-tools` — fstrim/nsenter, for Longhorn

Both nodes run this schematic. Earlier schematics were `e5912b95…` (amdgpu
only) and, in older docs, `b6ab12e…`. Storage details: [`talos-k8s/longhorn/`](https://github.com/hanthor/dotfiles/blob/master/talos-k8s/longhorn/README.md).

```yaml
machine:
  install:
    image: factory.talos.dev/installer/3a33ec6dfc8cfd61d2a3db3caf97894f31e913952d71ce3c3fbbe565a3f08339:v1.13.2
    disk: /dev/nvme0n1
```

After install, the node exposes `/dev/dri/card0`, `/dev/dri/renderD128`, and `/dev/kfd` on the host.

> **Talos version note:** Pinned to `v1.13.2`. `v1.13.3` had multi-arch registry pull errors on AMD64 at the time of writing.

### User volume for /var/mnt/storage

nvme0n1 is the **Crucial P3** (healthy, boot disk). The WD Black failed with I/O errors
and was replaced as the boot disk. Forgejo / local-path PVCs use a `directory`-type
user volume on the Crucial P3's EPHEMERAL partition:

```bash
# Apply the user volume config (idempotent):
talosctl -n <karnataka-ip> patch mc --patch @storage-volume.yaml
```

The patch is stored at [`talos-k8s/longhorn/storage-volume.yaml`](https://github.com/hanthor/dotfiles/blob/master/talos-k8s/longhorn/storage-volume.yaml).
It creates `/var/mnt/storage` as a directory on the EPHEMERAL partition.
The mount is automatically propagated into the kubelet namespace.

> **WD Black failure (2026-05-30):** The WD Black SN850X (`/dev/nvme1n1`)
> developed I/O errors on its META partition during the 35B model download stress test.
> Error: `error writing config to file: input/output error`. The drive should be
> physically replaced. In the meantime, do not configure it as a Talos install disk
> or user volume.

---

## 5. Cluster bootstrap

Configs are generated once with `talosctl gen config`, edited, and applied to each node. The generated files contain **cluster PKI secrets** (machine token, bootstrap token, shared secret) and are **not committed** — they live in Bitwarden.

### One-time generation

```bash
cd talos-k8s
talosctl gen config talos-k8s https://<bihar-ip>:6443
# Produces: controlplane.yaml, worker.yaml, talosconfig
```

Then patch `machine.install.image` and `machine.install.disk` on each (see `talos-k8s/README.md` for the schematic ID).

### Apply configs

```bash
talosctl apply-config --insecure --nodes <bihar-ip> --file controlplane.yaml
talosctl apply-config --insecure --nodes <karnataka-ip> --file worker.yaml

talosctl config endpoint <bihar-ip>
talosctl config node <bihar-ip>

talosctl bootstrap --nodes <bihar-ip>
talosctl kubeconfig                  # writes ~/.kube/config
```

### Seed Bitwarden with secrets

Once the cluster is up and you have working `~/.kube/config` and `~/.talos/config`:

```bash
just seed-kube     # uploads kubeconfig + talosconfig to Bitwarden as secure notes
```

Other workstations then pull them automatically:

```bash
just apply-tags kube
```

---

## 6. AMD GPU exposed to Kubernetes

The driver is loaded on the host (from the Talos image). Kubernetes needs two more pieces from ROCm to actually schedule on the GPU:

```bash
kubectl apply -f https://raw.githubusercontent.com/ROCm/k8s-device-plugin/master/k8s-ds-amdgpu-dp.yaml
kubectl apply -f https://raw.githubusercontent.com/ROCm/k8s-device-plugin/master/k8s-ds-amdgpu-labeller.yaml
```

Once the DaemonSets are running, `karnataka` exposes:

- `amd.com/gpu: 1` as an allocatable resource
- Labels such as `amd.com/gpu.product-name=AMD_Radeon_8060S_Graphics`, `amd.com/gpu.vram=64G`

Workloads request the GPU with:

```yaml
resources:
  limits:
    amd.com/gpu: "1"
```

---

## 7. Production workloads

All manifests live in [`talos-k8s/`](https://github.com/hanthor/dotfiles/tree/master/talos-k8s), organized by purpose:

```
talos-k8s/
├── ai/              Lemonade (LLM runtime)
├── appflowy/        AppFlowy Cloud (collaboration)
├── authentik/       Authentik (SSO)
├── forgejo/         Forgejo + runner + registry-mirror
├── hive/            Hive (AI agent swarm)
├── homepage/        Cluster landing page
├── infrastructure/  KubeVirt + Corral
├── kubestellar-hive/ KubeStellar multi-cluster hive
├── longhorn/        Storage (CSI, snapshots)
├── monitoring/      Prometheus + Grafana + metrics-server
├── n8n/             n8n (workflow automation)
├── networking/      Tailscale node configs
├── searxng/         SearXNG (self-hosted search)
├── testing-lab/     CI/CD test infrastructure
└── topolvm/         TopoLVM (dynamic LVM storage)
```

### Lemonade — AMD-optimized local AI runtime

Single-replica [Lemonade](https://lemonade-sdk.github.io/) omni-modal server on the Strix Halo APU.
Manifest: [`talos-k8s/ai/lemonade.yaml`](https://github.com/hanthor/dotfiles/blob/master/talos-k8s/ai/lemonade.yaml).

Lemonade is an AMD-optimized, open-source local AI runtime that auto-detects hardware and provides standard OpenAI-compatible endpoints for chat, vision, image generation, image editing, speech generation, and transcription. Built on llama.cpp, ONNX Runtime, whisper.cpp, and stable-diffusion.cpp.

Key env overrides (RDNA 3.5 needs special handling):

| Env var | Value | Why |
|---------|-------|-----|
| `HSA_OVERRIDE_GFX_VERSION` | `11.5.1` | Forces ROCm to treat gfx1151 as supported |
| `PYTORCH_ROCM_ARCH` | `gfx1151` | Compile shaders for exact arch |
| `HSA_XNACK` | `1` | Enables unified memory |
| `HSA_FORCE_FINE_GRAIN_PCIE` | `1` | Fine-grained VM access |

**Access:**
- LAN: `http://<karnataka-ip>:31305/v1` (NodePort)
- Tailscale: `https://lemonade.manatee-basking.ts.net/v1`

Model weights cached on `karnataka:/var/tmp/lemonade-cache` (HuggingFace) and `/var/tmp/lemonade-models` (llama models) via local-storage PersistentVolumes.

**Web UI:** Point a browser at `http://<karnataka-ip>:31305` for the built-in control panel to download models, configure endpoints, and test chat/vision/image generation.

### KubeVirt v1.8.2

Installed from upstream operator manifests:

```bash
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.2/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.2/kubevirt-cr.yaml
```

The `default` namespace is labelled `pod-security.kubernetes.io/enforce=privileged` so privileged virtualization pods can run.

### KubeVirt Manager (web UI)

Manifest: deployed from upstream bundle. Also see [`talos-k8s/infrastructure/`](https://github.com/hanthor/dotfiles/tree/master/talos-k8s/infrastructure) for KubeVirt CR and Corral VM dashboard.

```bash
kubectl apply -f https://raw.githubusercontent.com/kubevirt-manager/kubevirt-manager/main/kubernetes/bundled.yaml
```

Reachable at `https://kubevirt-manager.manatee-basking.ts.net` via the Tailscale ingress (manifest in cluster — not in this repo since it's a stock bundle).

Port-forward as fallback:

```bash
kubectl port-forward svc/kubevirt-manager 8080:8080 -n kubevirt-manager
# http://localhost:8080
```

---

### Additional services

All other production services have their own directory in [`talos-k8s/`](https://github.com/hanthor/dotfiles/tree/master/talos-k8s):

| Service | Directory | Description |
|---------|-----------|-------------|
| Forgejo | `forgejo/` | Git hosting + Actions CI/CD |
| Hive | `hive/` | AI coding agent swarm backed by Lemonade |
| Authentik | `authentik/` | SSO (passkeys, OAuth2/OIDC) — Helm |
| n8n | `n8n/` | Workflow automation — plain K8s manifest |
| AppFlowy Cloud | `appflowy/` | Collaborative workspace — commercial Helm chart |
| Grafana + Prometheus | `monitoring/` | kube-prometheus-stack + metrics-server |
| ArgoCD | (Helm) | GitOps deployment |
| Longhorn | `longhorn/` | Distributed block storage (CSI, snapshots) |
| KubeStellar Hive | `kubestellar-hive/` | KubeStellar multi-cluster hive |
| SearXNG | `searxng/` | Self-hosted metasearch |
| TopoLVM | `topolvm/` | Dynamic LVM-backed storage |
| Testing lab | `testing-lab/` | Argo Workflows CI/CD test infra |

Each directory has a `README.md` with deploy and operational instructions.

---

## 8. Tailscale operator (ingress)

The [Tailscale Operator](https://tailscale.com/kb/1236/kubernetes-operator) creates a Tailscale-side proxy pod for any `Ingress` resource with `ingressClassName: tailscale`. The proxy joins the tailnet with a name derived from the Ingress, and routes incoming traffic to the backing Service.

Example:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: lemonade
spec:
  ingressClassName: tailscale
  defaultBackend:
    service:
      name: lemonade
      port:
        number: 13305
  tls:
    - hosts:
        - lemonade
```

The operator namespace is `tailscale`. Auth keys are configured during operator install — see Tailscale docs for renewal.

---

## 9. Day-to-day operations

### From your workstation

The `kube` role syncs `~/.kube/config` and `~/.talos/config` from Bitwarden, so on any desktop:

```bash
kubectl get pods -A
talosctl -n <bihar-ip> health
talosctl -n <karnataka-ip> dmesg | grep -i amdgpu
```

### Common kubectl

```bash
kubectl get nodes -o wide
kubectl top nodes                        # requires metrics-server (monitoring/metrics-server.yaml)
kubectl logs -f deployment/lemonade
kubectl describe pod -l app=lemonade    # check GPU scheduling / events
```

### Common talosctl

```bash
talosctl -n <karnataka-ip> list /dev/dri/   # confirm GPU devices visible to host
talosctl -n <karnataka-ip> services         # systemd-equivalent services
talosctl -n <bihar-ip> etcd status      # control-plane etcd health
talosctl -n <bihar-ip> logs kubelet
talosctl -n <bihar-ip> reboot           # graceful reboot
```

---

## 10. Reinstall procedure

If a node is wiped or replaced:

1. **Boot Talos ISO** on the node (or PXE if you set that up separately). Default Talos boots into maintenance mode and accepts an apply-config.
2. **Apply config**:
   ```bash
   talosctl apply-config --insecure --nodes <node-ip> --file <controlplane|worker>.yaml
   ```
3. **Bootstrap etcd** (control plane only, first time):
   ```bash
   talosctl bootstrap --nodes <bihar-ip>
   ```
4. **Verify**:
   ```bash
   talosctl -n <bihar-ip> health
   kubectl get nodes
   ```
5. **Create user volume** (karnataka/worker only):
   ```bash
   talosctl -n <karnataka-ip> patch mc --patch @talos-k8s/longhorn/storage-volume.yaml
   ```
6. **Create host directories** for local PVs (if re-creating from scratch):
   ```bash
   kubectl exec -n kube-system $(kubectl get pods -n kube-system --field-selector spec.nodeName=karnataka -l app=kube-flannel -o name) -- \
     mkdir -p /proc/1/root/var/tmp/lemonade-cache
     mkdir -p /proc/1/root/var/tmp/lemonade-models
   ```
7. **Re-apply workloads** (idempotent):
   ```bash
   kubectl apply -f https://raw.githubusercontent.com/ROCm/k8s-device-plugin/master/k8s-ds-amdgpu-dp.yaml
   kubectl apply -f https://raw.githubusercontent.com/ROCm/k8s-device-plugin/master/k8s-ds-amdgpu-labeller.yaml
   kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.2/kubevirt-operator.yaml
   kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.2/kubevirt-cr.yaml
   kubectl apply -f https://raw.githubusercontent.com/kubevirt-manager/kubevirt-manager/main/kubernetes/bundled.yaml
   kubectl apply -f talos-k8s/ai/lemonade.yaml
   ```

If only the worker was reset, the existing kubeconfig still works — only steps 1, 2, 5, and 6 are needed for that node, plus re-applying any DaemonSet pods.

> **WD Black failure:** Do not use the WD Black (`/dev/nvme1n1`) for installs or user volumes.
> Install only to the Crucial P3 (`/dev/nvme0n1`). Storage uses a directory-type volume
> on the Crucial P3's EPHEMERAL partition.

---

## 11. Troubleshooting

### `amd.com/gpu` shows `0` on karnataka

Check the device plugin actually scheduled and started:

```bash
kubectl -n kube-system get pods -l name=amdgpu-device-plugin-ds
kubectl -n kube-system logs -l name=amdgpu-device-plugin-ds --tail=50
talosctl -n <karnataka-ip> dmesg | grep -i amdgpu   # confirm driver loaded
talosctl -n <karnataka-ip> list /dev/dri/           # confirm devices exist
```

### Lemonade pod stuck in `ContainerCreating`

Most often: pulling models from HuggingFace. Check:

```bash
kubectl describe pod -l app=lemonade
kubectl get pv,pvc                       # confirm PVCs bound
```

### Tailscale Ingress not reachable

```bash
kubectl -n tailscale get pods            # operator + per-Ingress ts-* proxies
kubectl -n tailscale logs deploy/operator
tailscale status | grep -i <ingress-name>
```

### Talos node unresponsive

```bash
talosctl -n <ip> health --wait
talosctl -n <ip> dmesg --tail
talosctl -n <ip> reset                   # nuclear: wipes node, requires re-apply
```

### Container runtime crash (karnataka)

**Symptoms:**
- `kubectl get nodes` shows karnataka `NotReady`
- `kubectl describe node karnataka` shows `Ready: False` with `container runtime is down`
- All pods on karnataka stuck in `Terminating`/`Pending`
- Ping to karnataka still works (node is up, just CRI is dead)

**Root cause:** Memory pressure from simultaneous large container builds exhausts
karnataka's 62GB unified memory. The node runs Lemonade (48-56Gi), Argo Workflow image
builds, Forgejo Actions (podman-in-Docker), KubeVirt, and monitoring — when
multiple 4GB image builds run concurrently, containerd OOMs and crashes.

**Recovery:**
```bash
# Option 1: Graceful reboot via Talos
talosctl -n <karnataka-ip> reboot

# Option 2: Hard reboot via the NanoKVM (see network/kvm)
```

After reboot (~2 min), all pods recover automatically. PVC-backed services
(Forgejo, local-path PVs) survive.

**Prevention:**
- Don't run more than one large container build concurrently on karnataka
- Set `SKIP_CHUNKAH=1` for Forgejo builds (avoids extra 2GB memory spike)
- Consider moving non-GPU workloads to bihar or a third node
- The Forgejo runner has `timeout-minutes: 45` — builds that exceed this will be killed

---

## 12. Hummingbird/bootc migration (home only)

### Scope and acceptance status

This is a replacement OS and **new K3s cluster** for the two home nodes, not a
Talos upgrade. Bihar is the Intel server/control plane; Karnataka is the AMD
worker. **No physical migration has been performed.** The home cluster is still
powered down/in storage. Nothing here changes the
[AWS Talos cluster](../aws-k8s/cluster.md), its workloads, credentials, or nodes.
Sections 1–11 remain the Talos recovery handbook, not instructions for the new OS.

Image builds alone do not prove installation. The GitHub Actions acceptance
workflow builds both images and offline ISOs, drives the **real
`bootc-installer-tui`**, boots the installed disks without their ISOs, then
activates a disposable two-node K3s cluster. Passing CI evidence has **not yet
been recorded here**; consult the actual run and uploaded logs before relying
on it. VM acceptance cannot establish GPU, physical NIC, disk health, firmware,
or nested-virtualization readiness on the real machines.

### Image contents and state

The source is `server-images/Containerfile`, `compose.sh`, `nodes/`, and `rootfs/`.
Both targets use the digest-pinned Hummingbird Community `os-minimal` base,
without a desktop. Firmware (including AMD GPU/CPU, Intel microcode, Realtek,
and MediaTek support) comes through the digest-pinned Utah package factory.
That local repository is authenticated by its OCI digest, **not RPM signatures**.
The lower-priority Fedora 44 repository checks Fedora RPM signatures and supplies
missing storage dependencies; it does not replace the Hummingbird kernel.
The separate live-media build uses Hummingbird's `dracut-live` and
`systemd-boot-unsigned`, with missing dependencies such as fuse, parted, and
ntfs-3g supplied by signed Fedora RPMs. Those live additions do not modify the
embedded installed-system OCI payload.
K3s and its SELinux policy RPM are separately SHA256-pinned.

K3s is pinned to **`v1.36.1+k3s1`**, with embedded containerd, Flannel networking,
and embedded etcd on Bihar (`cluster-init: true`). Pod/service CIDRs remain
`10.244.0.0/16` and `10.96.0.0/12`; cluster DNS is `10.96.0.10`.
Bihar disables bundled Traefik, ServiceLB, and metrics-server: restore any needed
equivalents deliberately. This is one control plane, not HA.

NetworkManager, sshd, firewalld, and iSCSI services are enabled. Bihar enables
`k3s@server`; Karnataka enables `k3s@agent`, but both are gated by
`/etc/rancher/k3s/activate`. **No activation marker or cluster token is baked
into an image.** Automatic bootc fetch/apply services are masked so a reboot of
the only control plane is an explicit maintenance decision.

Mutable state includes `/etc/rancher/k3s`, `/var/lib/rancher/k3s` (including etcd
and containerd), user homes under `/var/home`, and these retained workload paths:

| Path | Purpose |
|------|---------|
| `/var/mnt/storage` | Bihar's K3s local-path default and existing host-path data |
| `/var/lib/longhorn` | Longhorn persistent storage |
| `/var/lib/lemonade-cache` | Lemonade cache, matching the current home PV manifest |
| `/var/lib/lemonade-models` | Lemonade models, matching the current home PV manifest |

The current `talos-k8s/ai/lemonade.yaml` uses `/var/lib/lemonade-*`. The offline
Talos node may still hold the data under `/var/tmp/lemonade-*`: back up those
source directories before wiping and restore into `/var/lib/lemonade-*` on the
new node. Creating an empty PV directory does not migrate the models.

### Back up before building a physical migration plan

Before **any disk wipe**, recover the old nodes if necessary and copy application
backups, PV data, models, manifests, and required secrets **off both machines**.
Inventory PV-to-node/path mappings, ownership, application restore procedures,
and Longhorn volumes; verify the backups can be read/restored independently.
An etcd snapshot is useful for Talos recovery, but **Talos etcd cannot be
directly restored into K3s**. A matching directory name is not a data migration.

Keep the old Bitwarden secure notes `kubeconfig` / `talosconfig` and their
`~/.kube/config` / `~/.talos/config` files. Also keep the separate AWS
`kubeconfig-aws-migration` / `talosconfig-aws-migration` notes and files unchanged.
Use a new home kubeconfig below; do not overwrite any of these.

**Karnataka's `/dev/nvme1n1` (WD Black) is failing: never select it.**
Only the healthy `/dev/nvme0n1` is a candidate, **after off-node backups and an
explicit physical operator choice**. Identify disks by model, serial, size,
and current contents at the console (`lsblk -o NAME,SIZE,MODEL,SERIAL,FSTYPE,MOUNTPOINTS`);
do not assume device enumeration is sufficient. Apply the same backup and
operator-choice gate to Bihar's intended `/dev/nvme0n1`.

### Build both targets and offline installation media

Run from this repository on a Linux builder with Podman, Go compatible with
Fisherman's `tui/go.mod`, Python 3, squashfs-tools (`mksquashfs`), dosfstools
(`mkfs.fat`), mtools (`mmd`, `mcopy`), and xorriso available. Local source
defaults are `~/dev/tuna-os/fisherman` and `~/dev/utah`; override with
`FISHERMAN_SRC` and `UTAH_SRC`. For the CI source selection, use Fisherman commit
`dc9920c6bdeb96fdf567cd968d8b632336a9c611` and Utah commit
`f2736b6b774551cc8971af85cedaa65a272354ee`; the Fisherman Go requirement is
`1.26.2`. The media builder compiles the real Fisherman backend and TUI from
these trees, not a substitute installer.

```bash
just server-images
# Produces localhost/home-k8s-bihar:testing and localhost/home-k8s-karnataka:testing.
mkdir -p artifacts/home-k8s
export FISHERMAN_SRC="$HOME/dev/tuna-os/fisherman"
export UTAH_SRC="$HOME/dev/utah"
# Choose canonical refs in a registry namespace you control.
export BIHAR_TARGET_REF=ghcr.io/hanthor/home-k8s-bihar:testing
export KARNATAKA_TARGET_REF=ghcr.io/hanthor/home-k8s-karnataka:testing
just server-installer bihar "$BIHAR_TARGET_REF" artifacts/home-k8s/bihar-installer.iso
just server-installer karnataka "$KARNATAKA_TARGET_REF" artifacts/home-k8s/karnataka-installer.iso
```

The target references above are **day-2 tracking metadata**, not downloads needed
by the offline installation. Each ISO embeds its matching unchanged OCI payload.
Neither these commands nor CI publish registry images. Refs may therefore be
unpublished. Before a later `bootc upgrade`, deliberately publish the intended
image to its canonical ref (with appropriate registry access) and verify the
digest; building an ISO does not make that ref available.

### Install through the actual TUI

For each node, first meet the backup/disk-selection gate above. Boot its matching
ISO in **UEFI mode with Secure Boot disabled**. At the live root console run:

```bash
bootc-installer-tui
```

1. Skip network configuration to use **DHCP**. The pinned TUI does not serialize
   selected network configuration; do not depend on it applying static addressing.
2. Choose **Custom URL** and enter `oci:/usr/share/home-k8s/payload`.
3. Choose the verified intended installation disk. Installation destroys its
   contents; do not choose the failing Karnataka secondary disk.
4. Choose **ext4**, and set the hostname to `bihar` or `karnataka` as appropriate.
5. Leave disk encryption disabled for the tested installation path. Encrypted
   installation is not covered by this acceptance run.
6. Create an **actual administrative user** with a strong password. Record it
   securely and check login/sudo after installation. Do not rely on root live
   access as an installed-system account.
7. Skip SSH-key import: this pinned TUI does not serialize imported keys into
   the installation. Add authorized keys securely after first login instead.
8. Review the destructive disk choice, install, shut down/reboot, and **remove
   the ISO** so the next boot is from the installed disk.

The live ISO is SELinux **permissive only** (`enforcing=0`, not `selinux=0`).
That exception belongs to live assembly, not the target. On the installed node,
verify `getenforce` prints **`Enforcing`**, `sudo -v` succeeds for the new user,
`bootc status` shows the intended target reference, and the corresponding K3s
unit is inactive before activation. Stop and resolve any mismatch before joining
the cluster. Install SSH keys and verify remote access using authenticated,
trusted connections; never paste private keys or cluster tokens into CI logs.

### Explicit activation and separate kubeconfig

Verify router DHCP reservations and actual addresses **before starting K3s**:
**Bihar `192.168.0.5`, Karnataka `192.168.0.6`**. The worker configuration and
server TLS SAN depend on Bihar's address. Make sure the isolated/new home
cluster cannot conflict with a running old cluster at those addresses.

On Bihar, as root:

```bash
touch /etc/rancher/k3s/activate
systemctl start k3s@server
k3s kubectl get nodes
```

Wait for the API/server to be healthy. Securely transfer
`/var/lib/rancher/k3s/server/node-token` from Bihar to
`/etc/rancher/k3s/token` on Karnataka. **Treat this server token as
cluster-admin-sensitive**, not as a harmless worker password. Use a verified SSH
connection or other authenticated encrypted channel; do not print it, commit it,
store it in artifacts, or copy it through chat. On Karnataka ensure the file is
owned by root and mode `0600` before activation:

```bash
chown root:root /etc/rancher/k3s/token
chmod 0600 /etc/rancher/k3s/token
touch /etc/rancher/k3s/activate
systemctl start k3s@agent
```

Securely copy Bihar's `/etc/rancher/k3s/k3s.yaml` to the workstation as
`~/.kube/config-home-hummingbird` (mode `0600`); change only its loopback API
endpoint to `https://192.168.0.5:6443`. Keep this admin credential out of Git and
logs. Use it explicitly instead of changing the old home or AWS kubeconfigs:

```bash
export KUBECONFIG="$HOME/.kube/config-home-hummingbird"
kubectl get nodes -o wide
kubectl wait --for=condition=Ready nodes/bihar nodes/karnataka --timeout=300s
```

### Restore home workloads and validate before cutover

Review and apply **only selected home workload manifests** from `talos-k8s/`.
Do not recursively apply that whole directory: it also contains AWS manifests.
Do not apply Talos machine patches, extension/schematic settings, or Talos-only
bootstrap configuration to K3s. Reconcile storage classes, node labels,
selectors, host paths, privileged-device access, and security requirements
against the new cluster before restoring applications.

Restore data from off-node backups to the intended node/path with correct
ownership and SELinux labels (use `restorecon` on restored host paths). Follow
application-consistent restore procedures rather than blindly copying running
databases or treating Longhorn's data directory as a complete backup. Validate
PVC binding, persistence after pod/node restarts, DNS, cross-node traffic,
ingress, application health, and data integrity before declaring a cutover.

On real Karnataka hardware, verify `amdgpu`, `/dev/kfd`, `/dev/dri`, the AMD
device plugin's allocatable GPU, and an actual Lemonade inference workload.
Verify `/dev/kvm`, firmware virtualization settings, the correct Intel/AMD KVM
modules, KubeVirt scheduling, and a real guest boot on the relevant nodes.
Build-time module checks and virtual acceptance do not establish these facts.

Use planned maintenance and fresh data/etcd backups for day-2 bootc updates.
**`bootc rollback` rolls back the OS deployment, not application data, etcd,
mutable `/etc` configuration, or PV contents.** A data rollback requires its
own tested restore plan; retain the Talos recovery material independently.

### Disposable VM acceptance (GitHub Actions and local)

GitHub Actions workflow [Home server images](../../../../.github/workflows/server-images.yml)
(`server-images.yml`) runs for matching pull requests and master pushes.
Once present on the default branch, it can also be dispatched on a review branch
with no inputs. It runs the build, offline media creation, real interactive TUI
installation for both targets, and installed-disk cluster acceptance. Its VMs
use an isolated virtual LAN plus QEMU NAT, not the physical home LAN. CI must
explicitly require KVM and fail if it is unavailable; no registry publication,
fleet deployment, or physical-disk access is part of this workflow.
It runs on `ubuntu-24.04` and uploads only `*.log`, `*.json`, and `*.txt` as
`home-server-images-diagnostics` with seven-day retention, not installed disks
or ISOs. Retain any needed evidence before those artifacts expire.

For local acceptance, install `uv`, QEMU x86_64, and OVMF, and use the ISO names
from the build commands above. These commands create disposable installed
qcow2 disks and per-node UEFI variable stores in the artifact directory:

```bash
uv run server-images/test-vm.py --artifacts artifacts/home-k8s --accel kvm install bihar
uv run server-images/test-vm.py --artifacts artifacts/home-k8s --accel kvm install karnataka
uv run server-images/test-vm.py --artifacts artifacts/home-k8s --accel kvm cluster
```

On a machine without usable KVM, explicitly replace `--accel kvm` with
`--accel tcg` in **all three commands**; this is slower emulation, not hardware
acceleration proof. The harness pins `pexpect==4.9.0` through its inline `uv`
dependency metadata. It drives the actual TUI, powers off, removes the ISO,
boots the installed UEFI disk, checks login/sudo, Enforcing SELinux, target
reference, and inactive K3s, then activates both nodes and checks Ready status,
cross-node traffic, DNS, and PVC behavior. Preserve the generated `*.log`,
`*.json`, and `*.txt` proof outputs with the CI run. **No passing result is
claimed by this procedure; record actual evidence after the run completes.**
