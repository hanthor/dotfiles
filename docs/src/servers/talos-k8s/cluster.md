# Historical Cluster Handbook — Talos Linux on Bihar + Karnataka

> **Historical architecture and recovery reference, not a current deployment.**
> Bihar's OS and services are unverified. Karnataka runs `projectbluefin/utah:testing`
> with `multi-user.target` and a single-node K3s `v1.36.5+k3s1` server bound to
> tailnet address `100.66.158.127`. KubeVirt `v1.9.1`, CDI and Corral are installed;
> `corral-vms/punjab` is staging, not a migrated replacement for active EC2 Punjab.
> On the current server, firewalld puts `cni0` in the internal zone and accepts
> pod subnet `10.42.0.0/16` to kubelet port `10250` on that tailnet address;
> internal-zone services, including SSH, are accessible from pods. NetworkPolicy
> enforcement is unverified. Utah is enforcing SELinux, but `k3s-selinux` is
> absent and K3s container SELinux is disabled.
>
> **Do not run the reinstall, reset, bootstrap, configuration, migration, or
> workload commands below against repurposed nodes.** They can wipe disks or
> alter systems. They are historical examples for a separately planned recovery,
> after identifying the target and safeguarding data. Kubernetes service URLs
> below are historical, not running service endpoints.
>
> Preserve `talos-k8s/`, the home `kubeconfig` / `talosconfig` files and
> Bitwarden notes, and the separate AWS recovery material. Matrix and the School,
> Reef and Hub Hives are documented on the [OCI Spindle VPS](../spindle-vps/README.md).
> The [AWS Talos cluster](../aws-k8s/cluster.md) was terminated on 2026-10-25.
>
> For a deliberate future Talos recovery, inspect and back up the actual PV data
> before applying `talos-k8s/ai/lemonade.yaml`: the manifest uses `/var/lib/…`,
> while the old data was recorded under `/var/tmp/…`. See
> [`migrate-pv-path.sh`](https://github.com/hanthor/dotfiles/blob/master/talos-k8s/ai/migrate-pv-path.sh)
> and the [AI prerequisites](https://github.com/hanthor/dotfiles/blob/master/talos-k8s/ai/README.md);
> neither the location nor survival of those models is verified now.

The following describes the former two-node Talos/Kubernetes cluster, its AMD
GPU workloads, and its recovery procedures as historical reference.

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

The former cluster was **not diskless** — Talos installed onto `/dev/nvme0n1` on each node and persisted across reboots. This does not establish current disk contents.

**Retained manifests:** [`talos-k8s/`](https://github.com/hanthor/dotfiles/tree/master/talos-k8s) in this repo.
**Retained secrets** (`talosconfig`, `controlplane.yaml`, `worker.yaml`, `kubeconfig`): Bitwarden, fetched onto workstations by the `kube` unit. Preserve them as recovery material.

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
| CPU             | Intel Core i7-13700K |
| Integrated GPU  | Intel UHD 770 |
| Boot disk       | `/dev/nvme0n1` |

---

## 3. Network

### LAN — flat home /24

DHCP/DNS are served by the home router, which hands out fixed addresses from its address-reservation table — see [Gateway](../../network/gateway/README.md). Older revisions of this page said dnsmasq on bihar; that predates Talos, which can't run it on the host.

| Host        | Address  | Former role                |
|-------------|----------|----------------------------|
| bihar       | reserved | K8s control plane, home services |
| karnataka   | reserved | K8s worker, LLM host |
| goa         | reserved | Raspberry Pi, fleet control |
| kvm         | reserved | NanoKVM (plugged into karnataka) |

The historical commands use `<bihar-ip>` / `<karnataka-ip>` for the nodes' LAN
addresses. The retained talosconfig endpoints and router reservations are not
evidence that a Talos API is present at those addresses now.

### Internet — data-capped

The home connection has a monthly data cap; exceeding it throttles to a crawl
until the next billing cycle.

> **May 2026:** The cap was hit (largely model downloads and image pulls) and
> the link was throttled for about a week. Lesson: budget large model
> downloads and bulk image pulls against the cap. LAN traffic is unaffected.

### Tailscale — `manatee-basking.ts.net`

The former cluster used the [Tailscale Operator](https://tailscale.com/kb/1236/kubernetes-operator) for ingress. The following URLs are historical, not running Kubernetes services.

| Former service      | Historical URL |
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

**Historical schematic ID (2026-06-11):** `3a33ec6dfc8cfd61d2a3db3caf97894f31e913952d71ce3c3fbbe565a3f08339`

**Extensions baked in:**
- `siderolabs/amdgpu` — AMD GPU kernel driver
- `siderolabs/iscsi-tools` — iscsid, for Longhorn block storage
- `siderolabs/util-linux-tools` — fstrim/nsenter, for Longhorn

Both nodes formerly used this schematic. Earlier schematics were `e5912b95…` (amdgpu
only) and, in older docs, `b6ab12e…`. Storage details: [`talos-k8s/longhorn/`](https://github.com/hanthor/dotfiles/blob/master/talos-k8s/longhorn/README.md).

```yaml
machine:
  install:
    image: factory.talos.dev/installer/3a33ec6dfc8cfd61d2a3db3caf97894f31e913952d71ce3c3fbbe565a3f08339:v1.13.2
    disk: /dev/nvme0n1
```

After install, the node exposes `/dev/dri/card0`, `/dev/dri/renderD128`, and `/dev/kfd` on the host.

> **Talos version note:** Pinned to `v1.13.2`. `v1.13.3` had multi-arch registry pull errors on AMD64 at the time of writing.

### Historical user volume for /var/mnt/storage

At the time, nvme0n1 was the **Crucial P3** (boot disk). The WD Black had failed
with I/O errors and was replaced as the boot disk. Forgejo / local-path PVCs used
a `directory`-type user volume on the Crucial P3's EPHEMERAL partition. Current
disk health and contents are not established by this record:

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

> **Historical example:** do not apply these configs or bootstrap repurposed nodes.

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

The following workloads and addresses describe the former cluster, not currently running services.

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

**Former access:**
- LAN: `http://<karnataka-ip>:31305/v1` (NodePort)
- Tailscale: `https://lemonade.manatee-basking.ts.net/v1`

Model weights were cached under `karnataka:/var/tmp/lemonade-cache` (HuggingFace) and `/var/tmp/lemonade-models` (llama models) via local-storage PersistentVolumes; their current state is unverified.

The former web UI was at `http://<karnataka-ip>:31305`; this is not a running-service claim.

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

Formerly reachable at `https://kubevirt-manager.manatee-basking.ts.net` via Tailscale ingress (stock bundle, not in this repo). This URL is historical.

Former port-forward fallback:

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

These commands are retained for a deliberately restored Talos cluster; they do not establish that one exists now. Do not reboot or change repurposed machines.

### From your workstation

The `kube` unit syncs the retained `~/.kube/config` and `~/.talos/config` from Bitwarden. Historical examples:

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

> **Destructive historical procedure: do not run against repurposed nodes.**
> Reinstalling or bootstrapping can destroy existing systems and data. Only use
> as reference for a separately planned recovery after confirming the target,
> disk identity, and independently restorable backups.

The former procedure for a wiped or replaced node was:

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

> **Historical WD Black failure:** The former procedure excluded `/dev/nvme1n1`
> and selected the Crucial P3 (`/dev/nvme0n1`). Do not treat this as a current
> disk selection: verify identity, health, contents and backups before any recovery.

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

**Historical root cause:** Memory pressure from simultaneous large container builds exhausted
karnataka's 62GB unified memory. The former Talos node ran Lemonade (48-56Gi), Argo Workflow image
builds, Forgejo Actions (podman-in-Docker), KubeVirt, and monitoring — when
multiple 4GB image builds ran concurrently, containerd OOMed and crashed.

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

This section records a proposed replacement OS and **new two-node K3s cluster**,
not a Talos upgrade or instructions for the current single-node K3s server on
Utah. Bihar's present OS and services are unverified. Do not install, switch,
activate, or configure these images on Karnataka or other existing hosts. The
procedures below and sections 1–11 are retained for historical context and recovery
planning only. The terminated [AWS Talos cluster's](../aws-k8s/cluster.md)
recovery material remains separate.

Image builds alone do not prove installation. The GitHub Actions acceptance
workflow builds all three images and offline ISOs, drives the **real
`bootc-installer-tui`**, boots the installed disks without their ISOs, and
switches the installed starter to Bihar before activating a separate disposable
two-node K3s cluster.
[Publication run 39493512586](https://github.com/hanthor/dotfiles/actions/runs/39493512586)
passed for release source `4ec3fa6470d6b02e7eaf1b0eaae03d1db05a31a7`: all three offline TUI
installs, installed-disk UEFI boot, admin login/sudo, Enforcing SELinux,
unenrolled Tailscale, and a real starter-to-Bihar bootc switch with exact digest,
reboot, and administrator/hostname/identity/`/var` persistence checks. Gated K3s
activation then passed two Ready nodes, cross-node HTTP, cluster DNS, and
local-path PVC data surviving writer-pod replacement. The reviewed PR also
[passed normal repository CI](https://github.com/hanthor/dotfiles/actions/runs/39490206821).

On **2026-10-20**, Playwright drove both installers through the **actual Corral
noVNC canvases** on disposable KubeVirt VMs. Both reached “Installation
Complete”; their ISO volumes were then detached before installed-disk boots.
Real admin-password login/sudo and Enforcing SELinux passed on both. The installed
cluster passed the same DNS, cross-node HTTP, and PVC pod-replacement scenario
used by CI. Bihar's Intel `kvm_intel` module loaded on this Intel Corral host;
that is not a test of a nested KubeVirt guest or the physical home machines.

The deployed Corral service reported its cluster unreachable, so acceptance used
a temporary localhost Corral dashboard against `admin@aws-migration`, without
changing the deployed service. All test VMs/disks were isolated in namespace
`home-k8s-acceptance`. Configure the disposable node LAN as `192.168.0.5/24`
and `192.168.0.6/24` **before activating K3s**: Corral's provider pod addresses
overlap this new cluster's `10.244.0.0/16` pod CIDR. The initial overlapping
setup reached Ready nodes and working DNS but failed cross-node HTTP; the
non-overlapping guest LAN passed without changing the images' production
network configuration. Changing an already-initialized embedded-etcd server's
IP also requires its membership to be corrected; do not initialize it with the
provider pod IP in the first place.

Native Corral media predates publication-only OCI label changes; it is not
byte-identical to the subsequently rebuilt release. The publication dispatch
repeats complete KVM acceptance on the exact bytes it publishes. Corral evidence
is saved under `~/.local/share/home-k8s-build/` on the acceptance controller:
`corral-{bihar,karnataka}-install-complete.webp`,
`corral-{bihar,karnataka}-installed-boot.webp`,
`corral-installed-kubernetes.webp`, and `corral-cluster-proof.txt`.

The optional starter also passed a **2026-10-20** Playwright/noVNC installation
in namespace `home-k8s-starter-acceptance`, followed by ISO detachment and an
installed-disk UEFI boot. Actual admin-password login/sudo, hostname
`starter-smoke`, Enforcing SELinux, absent K3s role/configuration, driver/firmware
payload checks, and the canonical starter bootc reference passed. The real
installed `tailscaled` daemon was active and responsive in **NeedsLogin**, with
no tailnet and root-owned `0700` state; no VM was enrolled into the fleet.
The dedicated `tailscale0` SSH firewall zone was present. All disposable VMs,
PVCs, namespaces, and temporary Corral/upload services were removed afterward.

That native starter ISO was built from source
`2f8be86e3f98782f8dc7857e688e274318494f5b`, is **2,057,453,568 bytes**, and has SHA256
`1dc796f217e2d4ce6140511bed59399d2e031092299e2fa09e0436bea305ee27`.
Evidence is under `~/.local/share/home-k8s-build/unified-starter-native/`:
`corral-starter-install-summary.png`, `corral-starter-install-complete.png`,
`corral-starter-admin-sudo.png`, `corral-starter-installed-tailscale.png`, and
`corral-starter-installed-proof.txt`. These are native acceptance artifacts,
not a claim that the later publication rebuild is byte-identical.

VM acceptance cannot establish GPU, physical NIC, disk health, firmware,
or nested-virtualization readiness on the real machines. The recorded runner
was AMD EPYC: Bihar's Intel-only `kvm_intel` preload fails in that VM, so its
module-load unit is not evidence of working Intel virtualization. Verify that
unit and a real KubeVirt guest on physical Bihar before cutover.

### Image contents and state

The source is `server-images/Containerfile`, `compose.sh`, `nodes/`, and `rootfs/`.
The earlier targets used a digest-pinned Hummingbird Community `os-minimal`
base without a desktop. The proposed targets now use Utah; see the
[current image guide](../home-k8s-images.md). Bihar/Karnataka images were
proposed as direct installation paths; `starter` was optional for future
x86_64 AMD/Intel nodes. These are not current deployment instructions.
Explicit AMD/Intel GPU and CPU, Intel Wi-Fi, Realtek, MediaTek, Atheros, and
Broadcom firmware subpackages come through the digest-pinned Utah package factory.
That local repository is authenticated by its OCI digest, **not RPM signatures**.
The lower-priority Fedora 44 repository checks Fedora RPM signatures and supplies
missing storage dependencies; it does not replace the Hummingbird kernel.
The separate live-media build uses Hummingbird's `dracut-live` and
`systemd-boot-unsigned`, with missing dependencies such as fuse, parted, and
ntfs-3g supplied by signed Fedora RPMs. Those live additions do not modify the
embedded installed-system OCI payload.
K3s and its SELinux policy RPM are separately SHA256-pinned.

The common hardware payload includes:

| Hardware | Shipped support |
|---|---|
| Bihar: Intel Core i7-13700K / UHD 770 | Intel microcode, `i915` and its firmware, `kvm_intel`; the `xe` driver/firmware is also available |
| Karnataka: Strix Halo / Radeon 8060S (`gfx1151`) | `amdgpu`, `gc_11_5_1` GPU firmware, AMD microcode, `kvm_amd` |
| Karnataka: MediaTek MT7925 Wi-Fi | `mt7925e` plus its Wi-Fi code and patch firmware |
| Karnataka: Realtek RTL8126 Ethernet | `r8169` plus Realtek NIC firmware |
| Other common Wi-Fi families | Intel `iwlwifi`, Realtek `rtw89`, Atheros/Qualcomm `ath9k`/`ath10k`/`ath11k`/`ath12k`, Broadcom `brcmfmac`, and their selected firmware packages |

`NetworkManager-wifi` supplies the actual Wi-Fi backend, with `wpa_supplicant`
for authentication. After installed-system login, connect interactively with
`sudo nmcli --ask device wifi connect "your-ssid"`; never put Wi-Fi credentials
in image source or command-line password arguments. Live-session network
configuration is not copied by the pinned installer. Driver/module/firmware
presence is checked during builds and starter acceptance, but **physical RF,
GPU compute, device passthrough, and board-specific compatibility remain untested**.
This is not an ARM image or a proprietary NVIDIA/CUDA stack.

K3s is pinned to **`v1.36.1+k3s1`**, with embedded containerd, Flannel networking,
and embedded etcd on Bihar (`cluster-init: true`). Pod/service CIDRs remain
`10.244.0.0/16` and `10.96.0.0/12`; cluster DNS is `10.96.0.10`.
Bihar disables bundled Traefik, ServiceLB, and metrics-server: restore any needed
equivalents deliberately. This is one control plane, not HA.

NetworkManager, sshd, firewalld, Tailscale, and iSCSI services are enabled on all
three images. Bihar enables `k3s@server`; Karnataka enables `k3s@agent`, but
both are gated by `/etc/rancher/k3s/activate`. The starter selects neither role
and supplies no hostname, K3s configuration, or cluster endpoint.
**No activation marker, cluster token, Tailscale auth key, or enrolled identity
is baked into an image.** Automatic bootc fetch/apply services are masked so a
reboot of the only control plane is an explicit maintenance decision.
NFS GSSAPI state directories are initialized privately (`0700`) through
tmpfiles before the daemon's sandbox is assembled; CI requires `gssproxy` to
start successfully with SELinux enforcing.

Mutable state includes `/etc/rancher/k3s`, `/var/lib/rancher/k3s` (including etcd
and containerd), user homes under `/var/home`, and these retained workload paths:

| Path | Purpose |
|------|---------|
| `/var/mnt/storage` | Bihar's K3s local-path default and existing host-path data |
| `/var/lib/longhorn` | Longhorn persistent storage |
| `/var/lib/lemonade-cache` | Lemonade cache, matching the current home PV manifest |
| `/var/lib/lemonade-models` | Lemonade models, matching the current home PV manifest |

The retained `talos-k8s/ai/lemonade.yaml` uses `/var/lib/lemonade-*`. The former
Talos node was recorded with data under `/var/tmp/lemonade-*`; its present
contents are unverified. Before any recovery, inspect and back up source data
independently. Creating an empty PV directory does not migrate models.

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

**Karnataka's `/dev/nvme1n1` (WD Black) was reported failing: never select it
without an independent assessment.** The former plan named `/dev/nvme0n1` as a
candidate, not as permission to overwrite the current Utah/K3s server. Any future
disk choice requires off-node backups and an explicit physical operator decision.
Identify disks by model, serial, size, and current contents at the console
(`lsblk -o NAME,SIZE,MODEL,SERIAL,FSTYPE,MOUNTPOINTS`); do not assume device
enumeration or historical health. Apply the same gate to Bihar.

### Build node images and optional starter media

Run from this repository on a Linux builder with Podman, Go compatible with
Fisherman's `tui/go.mod`, Python 3, squashfs-tools (`mksquashfs`), dosfstools
(`mkfs.fat`), mtools (`mmd`, `mcopy`), and xorriso available. Local source
defaults are `~/dev/tuna-os/fisherman` and `~/dev/utah`; override with
`FISHERMAN_SRC` and `UTAH_SRC`. For the CI source selection, use Fisherman commit
`014e704be5f7365c4a1ccdef37fcadf97ade792a` and Utah commit
`f2736b6b774551cc8971af85cedaa65a272354ee`; the Fisherman Go requirement is
`1.26.2`. The media builder compiles the real Fisherman backend and TUI from
these trees, not a substitute installer. Use a clean Fisherman checkout at that
revision: it includes the target-disk OCI staging fix from
the merged [Fisherman PR 345](https://github.com/tuna-os/fisherman/pull/345), required for
offline installation without exhausting the live filesystem.

```bash
just server-images
# Produces localhost/home-k8s-{starter,bihar,karnataka}:testing.
mkdir -p artifacts/home-k8s
export FISHERMAN_SRC="$HOME/dev/tuna-os/fisherman"
export UTAH_SRC="$HOME/dev/utah"
# Choose canonical refs in a registry namespace you control.
export BIHAR_TARGET_REF=ghcr.io/hanthor/home-k8s-bihar:testing
export KARNATAKA_TARGET_REF=ghcr.io/hanthor/home-k8s-karnataka:testing
just server-installer bihar "$BIHAR_TARGET_REF" artifacts/home-k8s/bihar-installer.iso
just server-installer karnataka "$KARNATAKA_TARGET_REF" artifacts/home-k8s/karnataka-installer.iso
# Optional: a hardware-generic install with no selected cluster role.
just server-installer starter ghcr.io/hanthor/home-k8s-starter:testing artifacts/home-k8s/starter-installer.iso
```

The target references above are **day-2 tracking metadata**, not downloads needed
by the offline installation. Each ISO embeds its matching unchanged OCI payload.
These local commands and PR/push acceptance do not publish registry images.
Before `bootc upgrade`, publish the intended image to its canonical ref and verify
the digest; building an ISO alone does not make that ref available.

To build just one profile, use `just server-image bihar`, `just server-image
karnataka`, or `just server-image starter`. The canonical recipe disables
Podman's injected `/etc/hostname` so image composition can clear the base hostname
before applying a specialization. The UEFI media keeps its boot files inside
the FAT ESP rather than duplicating them as loose ISO files; the embedded
installed-system payload is unchanged by that size reduction.

### Publish accepted images and installation media

Published acceptance release:
[**home-k8s-20261021**](https://github.com/hanthor/dotfiles/releases/tag/home-k8s-20261021).
These are public **prerelease** artifacts, not proof of physical hardware
readiness. All three profiles' date tags and `testing` channels passed anonymous
GHCR access and match the exact tested payloads and source revision.

| Profile | Published image | Offline installer ISO |
|---|---|---|
| Bihar | `ghcr.io/hanthor/home-k8s-bihar:20261021` | [bihar-installer.iso](https://github.com/hanthor/dotfiles/releases/download/home-k8s-20261021/bihar-installer.iso) |
| Karnataka | `ghcr.io/hanthor/home-k8s-karnataka:20261021` | [karnataka-installer.iso](https://github.com/hanthor/dotfiles/releases/download/home-k8s-20261021/karnataka-installer.iso) |
| Optional starter | `ghcr.io/hanthor/home-k8s-starter:20261021` | [starter-installer.iso](https://github.com/hanthor/dotfiles/releases/download/home-k8s-20261021/starter-installer.iso) |

Download [SHA256SUMS](https://github.com/hanthor/dotfiles/releases/download/home-k8s-20261021/SHA256SUMS)
and [provenance.json](https://github.com/hanthor/dotfiles/releases/download/home-k8s-20261021/provenance.json)
from the same release; the latter records image digests, exact source/upstream
revisions, and the acceptance run. OCI archives, media contracts, and the
[starter-switch proof](https://github.com/hanthor/dotfiles/releases/download/home-k8s-20261021/starter-switch-proof.txt)
are also release assets. The publisher treats date tags as write-once; use the
recorded `@sha256:` digest when a registry reference must be intrinsically immutable.
The older `20261020` release remains available but predates the optional starter
and completed GPU/Wi-Fi firmware and host Tailscale payload.

Publication is an explicit **master-only** dispatch, after interactive Corral
acceptance. It repeats all three real offline TUI installations, the installed
starter's bootc switch, and the two-node Kubernetes scenario before transferring
any release artifacts:

```bash
gh workflow run server-images.yml --repo hanthor/dotfiles --ref master \
  -f publish=true -f version=20261022
```

Choose an unused, valid `YYYYMMDD` date; `20261020` and `20261021` are already published.
Ordinary PR/push runs and manual runs
with `publish=false` remain read-only. Only the separate publishing job receives
registry/release write permissions; it pushes the exact accepted OCI archives,
not rebuilt images. It publishes `ghcr.io/hanthor/home-k8s-{starter,bihar,karnataka}`
with immutable date tags and the mutable `testing` channel, plus the public
GitHub prerelease `home-k8s-YYYYMMDD` (not the repository's latest stable release).
Assets include all three tested ISOs, OCI archives, media contracts, checksums,
source/upstream revisions, registry digests, explicit acceptance markers, and
the sanitized starter-switch proof.
The canonical `just server-images` build records this repository's Git revision
in the OCI source/revision labels, rather than inheriting Hummingbird's revision.
Installed VM disks and credentials are never release assets.

New GitHub container packages default to **private**, even when linked to a
public repository. The packages above are already public. For a new package,
change visibility in its GitHub package settings if necessary. The publisher
refuses to create the release until anonymous access to both image tags succeeds.
If this gate fails,
change visibility and rerun **only the failed publishing job within one day**:
the accepted artifact transfer has one-day retention. Identical existing date
tags are reused; different content or an existing release/tag name is rejected.
Never rebuild over an immutable date tag.

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
4. Choose **ext4**, and set the hostname to `bihar` or `karnataka` as appropriate,
   or a unique hostname for a new starter installation.
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

### Optional starter and a deliberate image switch

The starter is not a third cluster node and does not join anything on first boot.
It installs the same hardware, storage, Tailscale, and K3s tooling, but neither
K3s instance is enabled and there is no default K3s configuration. Install Bihar
and Karnataka directly when replacing those machines; the starter is an optional
base for additional machines or a later switch to another bootc image.

For example, to adopt Bihar's server profile from an installed starter:

```bash
sudo bootc switch ghcr.io/hanthor/home-k8s-bihar:testing
sudo systemctl reboot
```

After reboot, inspect `sudo bootc status` and verify the **booted** image, not
merely a staged deployment. The administrator, chosen hostname, and `/var` state
survive; a switch does not rename the host or create the K3s activation marker.
`/etc` uses a three-way merge, so review existing configuration rather than
assuming the destination image replaces it.

The named profiles are **home-machine specializations**, not generic role
templates: they contain fixed K3s node names, home addresses, and CPU-specific
module preloads. On additional machines, use an appropriate derived image or
review those defaults before activation, especially `node-name`, server address,
TLS SANs, and virtualization modules. The starter also retains the common
home-LAN firewall policy; new sites need an explicit network-policy review.

### Enroll host Tailscale after installation

The pinned Utah factory supplies Tailscale **1.98.8**. `tailscaled` starts
automatically but remains **NeedsLogin** until the operator enrolls that node.
On the installed system—not the live ISO—run:

```bash
sudo tailscale up --hostname="$(uname -n)" --advertise-tags=tag:fleet \
  --accept-dns=false --accept-routes=false
tailscale status
```

Complete the displayed login URL using the fleet tailnet account; `tag:fleet`
requires the corresponding tag-owner permission. This keeps the existing fleet
tag convention without importing tailnet routes or replacing the node's DNS,
which could conflict with the home/Flannel networks. No subnet routes, exit-node
service, or Tailscale SSH are enabled automatically.

The dedicated `tailscale0` firewalld zone allows ordinary SSH only; it does not
open the Kubernetes API, kubelet, VXLAN, or NodePorts to every tailnet peer.
Tailnet ACLs and installed SSH authorized keys still govern access. Host Tailscale
does not replace Flannel or the separate in-cluster Tailscale Operator.

Node keys and enrollment state live under private, root-owned
`/var/lib/tailscale` (`0700`) and survive bootc updates/switches. Never bake that
directory into an image or copy it between machines. A clean reinstall needs its
own enrollment; a live-session identity is not migrated by this installer.
CI checks the real installed daemon's unauthenticated state and private storage
with SELinux enforcing; it does **not** enroll disposable VMs into the fleet.

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

GitHub Actions workflow [Home server images](https://github.com/hanthor/dotfiles/actions/workflows/server-images.yml)
(`server-images.yml`) runs for matching pull requests and master pushes.
Manual dispatch defaults to acceptance only (`publish=false`); review branches
cannot publish. Acceptance builds all three images/ISOs, installs each through
the real TUI, and checks installed-disk boot, admin/sudo, Enforcing SELinux,
unenrolled Tailscale, and gated K3s. It switches the installed starter to the exact
new Bihar payload through a loopback-only registry, verifies the staged digest,
reboots, and checks the **booted** digest plus persistent admin/hostname/identity
and `/var` data. The fixture registry, starter disk, and NVRAM are removed before
the two-node cluster scenario. The VMs use an isolated virtual LAN plus QEMU NAT, not the physical
home LAN. CI requires KVM and fails if it is unavailable. No fleet deployment
or physical-disk access occurs, including on a publication dispatch.
It runs on `ubuntu-24.04` and uploads `*.log`, `*.json`, and `*.txt` diagnostics
as `home-server-images-diagnostics` with seven-day retention, never installed
disks. Only an explicit master publication retains the exact tested ISOs and
exports an allowlisted, one-day release-artifact transfer to the publishing job
described above. Retain any needed diagnostics before they expire.

For local acceptance, install `uv`, QEMU x86_64, Skopeo, and OVMF, and use the ISO names
from the build commands above. These commands create disposable installed
qcow2 disks and per-node UEFI variable stores in the artifact directory:

```bash
uv run server-images/test-vm.py --artifacts artifacts/home-k8s --accel kvm install starter
uv run server-images/test-vm.py --artifacts artifacts/home-k8s --accel kvm install bihar
uv run server-images/test-vm.py --artifacts artifacts/home-k8s --accel kvm install karnataka
uv run server-images/test-vm.py --artifacts artifacts/home-k8s --accel kvm cluster
```

To exercise a published-image switch on that installed starter, resolve the
immutable date tag's digest first (the guest needs outbound registry access):

```bash
image=ghcr.io/hanthor/home-k8s-bihar:20261021
digest=$(skopeo inspect --format '{{.Digest}}' "docker://$image")
uv run server-images/test-vm.py --artifacts artifacts/home-k8s --accel kvm \
  switch-starter --image "$image" --expected-digest "$digest"
```

`starter-switch-proof.txt` records only explicit successful checks and public
image references/digests, never the administrator password or private state.
The workflow's fixture instead uses the exact newly built Bihar archive before
publication, binds its HTTP registry only to `127.0.0.1:5000`, and scopes its
temporary insecure-registry setting to `10.0.2.2:5000` inside the disposable guest.

On a machine without usable KVM, explicitly replace `--accel kvm` with
`--accel tcg` in **every command**; this is slower emulation, not hardware
acceleration proof. The harness pins `pexpect==4.9.0` through its inline `uv`
dependency metadata. It drives the actual TUI, powers off, removes the ISO,
boots the installed UEFI disk, checks login/sudo, Enforcing SELinux, target
reference, and inactive K3s, then activates both nodes and checks Ready status,
cross-node traffic, DNS, and PVC behavior. Preserve the generated `*.log`,
`*.json`, and `*.txt` proof outputs with the CI run. The passing run and physical
hardware limitations are recorded under “Scope and acceptance status” above.
