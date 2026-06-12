# Cluster Handbook — Talos Linux on Bihar + Karnataka

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

---

## 1. Overview

```
┌──────────────────────────────────────────────────────────────┐
│                       Kubernetes v1.36.1                      │
│                        (Talos v1.13.2)                        │
│                                                               │
│   ┌────────────────────────┐   ┌────────────────────────┐    │
│   │  bihar  (control plane)│   │ karnataka  (worker)    │    │
│   │  192.168.0.5           │   │ 192.168.0.6            │    │
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

**Source of truth for manifests:** [`talos-k8s/`](../talos-k8s/) in this repo.
**Source of truth for secrets** (`talosconfig`, `controlplane.yaml`, `worker.yaml`, `kubeconfig`): Bitwarden, fetched onto your workstation by the `kube` role.

---

## 2. Hardware

### Karnataka (worker)

| Component       | Detail |
|-----------------|--------|
| CPU             | AMD Ryzen AI MAX+ 395 (Strix Halo) — 16 cores / 32 threads, 5.18 GHz boost |
| RAM             | 62 GB unified memory (CPU + GPU share via UMA) |
| GPU             | AMD Radeon 8060S — RDNA 3.5 (`gfx1151`), integrated |
| NIC             | Realtek RTL8126 5GbE (`enp191s0`) — MAC `9C:BF:0D:00:E5:0F` |
| WiFi            | [MediaTek MT7925](https://www.mediatek.com/products/broadband-wifi/mediatek-filogic-380) Wi-Fi 7 |
| Boot disk       | Crucial P3 1TB (`/dev/nvme0n1`, serial `24394B495110`) |
| Secondary       | WD Black SN850X 1TB (`/dev/nvme1n1`, serial `251623804191`) — **FAILING** (I/O errors). Do not use. Replace with new drive. |

### Bihar (control plane)

| Component       | Detail |
|-----------------|--------|
| CPU             | Intel x86_64 |
| NIC             | MAC `A8:A1:59:E1:6D:84` |
| Boot disk       | `/dev/nvme0n1` |
| Role on LAN     | DHCP, DNS (dnsmasq) |

---

## 3. Network

### LAN — `192.168.0.0/24`

DHCP/DNS served by **dnsmasq** on bihar. All assignments static via MAC.

| Host        | IP             | MAC                  | Role                       |
|-------------|----------------|----------------------|----------------------------|
| bihar       | `192.168.0.5`  | `A8:A1:59:E1:6D:84`  | K8s control plane, home services |
| karnataka   | `192.168.0.6`  | `9C:BF:0D:00:E5:0F`  | K8s worker, LLM host |
| raspberrypi | `192.168.0.10` | `D8:3A:DD:E9:C7:1D`  | Pi |
| kvm         | `192.168.0.99` | `48:DA:35:6F:A9:20`  | NanoKVM (plugged into karnataka) |

Run `just inventory` to rescan with nmap.

### Internet — Airtel India / capped

Airtel India home internet with a **3,333 GB/month** data cap. Exceeding the cap throttles
to **1.5 Mbps** until the next billing cycle.

> **May 31, 2026:** Cap hit at ~3,333 GB. Throttled to 1.5 Mbps until **June 8, 2026**.
> No large model downloads, image pulls, or bulk data transfers until then.
> Local LAN (192.168.0.0/24) is unaffected.

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
only) and, in older docs, `b6ab12e…`. Storage details: [`talos-k8s/longhorn/`](../../../talos-k8s/longhorn/README.md).

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
talosctl -n 192.168.0.6 patch mc --patch @storage-volume.yaml
```

The patch is stored at [`talos-k8s/longhorn/storage-volume.yaml`](../talos-k8s/longhorn/storage-volume.yaml).
It creates `/var/mnt/storage` as a directory on the EPHEMERAL partition.
The mount is automatically propagated into the kubelet namespace.

> **WD Black failure (2026-05-30):** The WD Black SN850X (`/dev/nvme1n1`, serial `251623804191`)
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
talosctl gen config talos-k8s https://192.168.0.5:6443
# Produces: controlplane.yaml, worker.yaml, talosconfig
```

Then patch `machine.install.image` and `machine.install.disk` on each (see `talos-k8s/README.md` for the schematic ID).

### Apply configs

```bash
talosctl apply-config --insecure --nodes 192.168.0.5 --file controlplane.yaml
talosctl apply-config --insecure --nodes 192.168.0.6 --file worker.yaml

talosctl config endpoint 192.168.0.5
talosctl config node 192.168.0.5

talosctl bootstrap --nodes 192.168.0.5
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

All manifests live in [`talos-k8s/`](../../../talos-k8s/), organized by purpose:

```
talos-k8s/
├── ai/              Lemonade (LLM runtime)
├── appflowy/        AppFlowy Cloud (collaboration)
├── authentik/       Authentik (SSO)
├── forgejo/         Forgejo + runner + registry-mirror
├── hive/            Hive (AI agent swarm)
├── homepage/        Cluster landing page
├── infrastructure/  KubeVirt + Corral
├── longhorn/        Storage (CSI, snapshots)
├── monitoring/      Prometheus + Grafana + metrics-server
├── n8n/             n8n (workflow automation)
├── networking/      Tailscale node configs
└── testing-lab/     CI/CD test infrastructure
```

### Lemonade — AMD-optimized local AI runtime

Single-replica [Lemonade](https://lemonade-sdk.github.io/) omni-modal server on the Strix Halo APU.
Manifest: [`talos-k8s/ai/lemonade.yaml`](../../../talos-k8s/ai/lemonade.yaml).

Lemonade is an AMD-optimized, open-source local AI runtime that auto-detects hardware and provides standard OpenAI-compatible endpoints for chat, vision, image generation, image editing, speech generation, and transcription. Built on llama.cpp, ONNX Runtime, whisper.cpp, and stable-diffusion.cpp.

Key env overrides (RDNA 3.5 needs special handling):

| Env var | Value | Why |
|---------|-------|-----|
| `HSA_OVERRIDE_GFX_VERSION` | `11.5.1` | Forces ROCm to treat gfx1151 as supported |
| `PYTORCH_ROCM_ARCH` | `gfx1151` | Compile shaders for exact arch |
| `HSA_XNACK` | `1` | Enables unified memory |
| `HSA_FORCE_FINE_GRAIN_PCIE` | `1` | Fine-grained VM access |

**Access:**
- LAN: `http://192.168.0.6:31305/v1` (NodePort)
- Tailscale: `https://lemonade.manatee-basking.ts.net/v1`

Model weights cached on `karnataka:/var/tmp/lemonade-cache` (HuggingFace) and `/var/tmp/lemonade-models` (llama models) via local-storage PersistentVolumes.

**Web UI:** Point a browser at `http://192.168.0.6:31305` for the built-in control panel to download models, configure endpoints, and test chat/vision/image generation.

### KubeVirt v1.8.2

Installed from upstream operator manifests:

```bash
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.2/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.2/kubevirt-cr.yaml
```

The `default` namespace is labelled `pod-security.kubernetes.io/enforce=privileged` so privileged virtualization pods can run.

### KubeVirt Manager (web UI)

Manifest: deployed from upstream bundle. Also see [`talos-k8s/infrastructure/`](../../../talos-k8s/infrastructure/) for KubeVirt CR and Corral VM dashboard.

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

All other production services have their own directory in [`talos-k8s/`](../../../talos-k8s/):

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
talosctl -n 192.168.0.5 health
talosctl -n 192.168.0.6 dmesg | grep -i amdgpu
```

### Common kubectl

```bash
kubectl get nodes -o wide
kubectl top nodes                        # requires metrics-server (not currently installed)
kubectl logs -f deployment/lemonade
kubectl describe pod -l app=lemonade    # check GPU scheduling / events
```

### Common talosctl

```bash
talosctl -n 192.168.0.6 list /dev/dri/   # confirm GPU devices visible to host
talosctl -n 192.168.0.6 services         # systemd-equivalent services
talosctl -n 192.168.0.5 etcd status      # control-plane etcd health
talosctl -n 192.168.0.5 logs kubelet
talosctl -n 192.168.0.5 reboot           # graceful reboot
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
   talosctl bootstrap --nodes 192.168.0.5
   ```
4. **Verify**:
   ```bash
   talosctl -n 192.168.0.5 health
   kubectl get nodes
   ```
5. **Create user volume** (karnataka/worker only):
   ```bash
   talosctl -n 192.168.0.6 patch mc --patch @talos-k8s/longhorn/storage-volume.yaml
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
talosctl -n 192.168.0.6 dmesg | grep -i amdgpu   # confirm driver loaded
talosctl -n 192.168.0.6 list /dev/dri/           # confirm devices exist
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
- Ping to `192.168.0.6` still works (node is up, just CRI is dead)

**Root cause:** Memory pressure from simultaneous large container builds exhausts
karnataka's 62GB unified memory. The node runs Lemonade (48-56Gi), Argo Workflow image
builds, Forgejo Actions (podman-in-Docker), KubeVirt, and monitoring — when
multiple 4GB image builds run concurrently, containerd OOMs and crashes.

**Recovery:**
```bash
# Option 1: Graceful reboot via Talos
talosctl -n 192.168.0.6 reboot

# Option 2: Hard reboot via NanoKVM at 192.168.0.99
```

After reboot (~2 min), all pods recover automatically. PVC-backed services
(Forgejo, local-path PVs) survive.

**Prevention:**
- Don't run more than one large container build concurrently on karnataka
- Set `SKIP_CHUNKAH=1` for Forgejo builds (avoids extra 2GB memory spike)
- Consider moving non-GPU workloads to bihar or a third node
- The Forgejo runner has `timeout-minutes: 45` — builds that exceed this will be killed
