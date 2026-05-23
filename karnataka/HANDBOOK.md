# Karnataka Server — Setup Handbook

> **AMD Ryzen AI MAX+ 395 · Flatcar Linux · Single-Node Kubernetes**  
> Netbooted, diskless, fully ephemeral. Everything you need to bring it back from zero.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Hardware Reference](#2-hardware-reference)
3. [Network Architecture](#3-network-architecture)
4. [PXE Boot Infrastructure](#4-pxe-boot-infrastructure)
5. [Operating System: Flatcar Container Linux](#5-operating-system-flatcar-container-linux)
6. [Ignition Configuration](#6-ignition-configuration)
7. [Kubernetes Cluster](#7-kubernetes-cluster)
8. [KubeSteller Stack](#8-kubestellar-stack)
9. [KubeVirt](#9-kubevirt)
10. [Tailscale Networking](#10-tailscale-networking)
11. [Complete Reinstallation Guide](#11-complete-reinstallation-guide)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. System Overview

**Karnataka** is a bare-metal server running as a single-node Kubernetes cluster. Its defining characteristic: it has **no persistent root filesystem**. The OS loads entirely into RAM on every boot via PXE (network boot), and all state — including the Kubernetes cluster — is rebuilt from scratch after each reboot using a declarative Ignition configuration and a documented installation sequence.

```
┌─────────────────────────────────────────────────────────┐
│                        KARNATAKA                        │
│              192.168.0.6 · AMD Ryzen AI MAX+ 395        │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │              Kubernetes v1.33 (kubeadm)          │   │
│  │                                                  │   │
│  │  ┌──────────────┐  ┌──────────────────────────┐ │   │
│  │  │  KubeSteller │  │        KubeVirt           │ │   │
│  │  │  Core + UI   │  │  (VM management in k8s)   │ │   │
│  │  └──────────────┘  └──────────────────────────┘ │   │
│  │  ┌──────────────┐  ┌──────────────────────────┐ │   │
│  │  │   Cilium CNI │  │  Tailscale Operator       │ │   │
│  │  └──────────────┘  └──────────────────────────┘ │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  OS: Flatcar 4593.2.1 · Kernel: 6.12.87-flatcar        │
│  Boot: PXE → RAM (tmpfs) · NVMe drives unused          │
└─────────────────────────────────────────────────────────┘
          │
          │ netboot (iPXE/TFTP/HTTP)
          ▼
┌─────────────────────────┐
│         BIHAR           │
│   192.168.0.5 · Proxmox │
│   PXE server + DHCP     │
└─────────────────────────┘
```

### Why diskless?

Running from RAM gives complete reproducibility. If something breaks, a reboot returns to a clean state. The Ignition config + this handbook are the single source of truth — the server is a recipe, not a snowflake.

### The golden rule

> **Reboot = full wipe.** Kubernetes, all workloads, and all cluster state are gone after a reboot. The NVMe drives are present but unmounted. Everything must be reprovisioned.

---

## 2. Hardware Reference

### Specifications

| Component        | Details                                                              |
|-----------------|----------------------------------------------------------------------|
| **CPU**         | AMD Ryzen AI MAX+ 395 (Strix Halo), 16 cores / 32 threads, 5.185 GHz boost |
| **RAM**         | 62 GB unified memory (CPU + GPU share)                              |
| **GPU**         | AMD Radeon 8060S (integrated, RDNA 3.5, Strix Halo)                |
| **NIC**         | Realtek RTL8126 5GbE (`enp191s0`)                                  |
| **WiFi**        | MediaTek MT7925 Wi-Fi 7 (160 MHz)                                  |
| **NVMe 0**      | WD Black SN850X 931.5 GB (`nvme0n1`) — has Flatcar partition layout, **unused** |
| **NVMe 1**      | Micron 2550 931.5 GB (`nvme1n1`) — single partition, **unused**    |
| **USB sda**     | 114.6 GB USB drive with Flatcar partition layout                    |

### Identity

| Property         | Value                         |
|-----------------|-------------------------------|
| **Hostname**    | `karnataka`                   |
| **LAN IP**      | `192.168.0.6` (DHCP-reserved) |
| **MAC address** | `9C:BF:0D:00:E5:0F`          |
| **NIC device**  | `enp191s0`                    |
| **Tailscale**   | `karnataka.manatee-basking.ts.net` |

### A note on storage

The two NVMe drives are visible at boot (`nvme0n1`, `nvme1n1`) but nothing mounts them. The system runs on `tmpfs` backed by the 62 GB of RAM. If persistent storage is ever needed, these drives are ready — they would need to be mounted and formatted (they currently contain old Flatcar partition tables from a previous disk-based setup).

---

## 3. Network Architecture

### Local LAN (`192.168.0.0/24`)

DHCP and DNS are served by **dnsmasq** running on **Bihar** (`192.168.0.5`, the Proxmox host). All assignments are static via MAC address.

| Host            | IP              | MAC                   | Role                          |
|----------------|-----------------|----------------------|-------------------------------|
| **bihar**       | `192.168.0.5`   | `A8:A1:59:E1:6D:84`  | Proxmox host, PXE server, homelab hub |
| **karnataka**   | `192.168.0.6`   | `9C:BF:0D:00:E5:0F`  | This server                   |
| **raspberrypi** | `192.168.0.10`  | `D8:3A:DD:E9:C7:1D`  | Raspberry Pi                  |
| **kvm**         | `192.168.0.99`  | `48:DA:35:6F:A9:20`  | KVM/NanoKVM host              |

### Tailscale overlay (`manatee-basking.ts.net`)

Tailscale provides authenticated remote access and serves as the ingress path for Kubernetes services exposed via the Tailscale Operator.

| Service              | Tailscale URL                                  |
|---------------------|------------------------------------------------|
| KubeSteller UI       | `https://kubestellar.manatee-basking.ts.net`   |
| KubeVirt API         | `https://kubevirt.manatee-basking.ts.net`       |
| Karnataka node       | `karnataka.manatee-basking.ts.net`              |

### Kubernetes internal networking

| Network          | CIDR              |
|-----------------|-------------------|
| Pod network      | `10.244.0.0/16`   |
| Service network  | `10.96.0.0/12`    |
| Cilium host IP   | `10.0.0.1/32`     |

---

## 4. PXE Boot Infrastructure

All PXE infrastructure lives on **Bihar**. This is what you need to understand when Karnataka boots.

### The boot chain

```
Karnataka powers on
      │
      ▼
NIC firmware sends DHCP discover
      │
      ▼ (dnsmasq on bihar, interface vmbr0)
DHCP offer includes:
  - IP: 192.168.0.6
  - Next server: 192.168.0.5
  - Boot file: iPXE/ipxe.efi  (UEFI) or
               iPXE/undionly.kpxe  (BIOS)
      │
      ▼
iPXE binary loads from TFTP (192.168.0.5)
      │
      ▼
iPXE runs /var/lib/pxe/tftp/autoexec.ipxe:
  chain http://192.168.0.5:8888/flatcar.ipxe
      │
      ▼
iPXE fetches flatcar.ipxe via HTTP:
  kernel flatcar_production_pxe.vmlinuz
         initrd=flatcar_production_pxe_image.cpio.gz
         flatcar.first_boot=1
         ignition.config.url=http://192.168.0.5:8888/karnataka-fresh.ign
  initrd flatcar_production_pxe_image.cpio.gz
  boot
      │
      ▼
Flatcar kernel + initramfs load into RAM
Ignition runs, provisions the system
OS fully boots (no disk writes)
```

### Files on Bihar (Consolidated in this Repository)

All of the configuration files required to run the PXE boot and provision Karnataka are now consolidated directly in this repository for reproducibility and version control:

*   **dnsmasq Config:** [dnsmasq-pxe.conf](file:///home/james/dev/karnataka/dnsmasq-pxe.conf) (active system path: `/etc/dnsmasq.d/pxe.conf`)
*   **iPXE Boot Scripts:**
    *   [autoexec.ipxe](file:///home/james/dev/karnataka/autoexec.ipxe) (active system path: `/var/lib/pxe/tftp/autoexec.ipxe`)
    *   [flatcar.ipxe](file:///home/james/dev/karnataka/flatcar.ipxe) (active system path: `/var/lib/pxe/http/flatcar.ipxe`)
*   **Ignition & Butane Configs:**
    *   [karnataka-fresh.bu](file:///home/james/dev/karnataka/karnataka-fresh.bu) (Source Butane configuration)
    *   [karnataka-fresh.ign](file:///home/james/dev/karnataka/karnataka-fresh.ign) (Transpiled Ignition JSON config; active system path: `/var/lib/pxe/http/karnataka-fresh.ign`)

The boot structure remains:
```
/var/lib/pxe/
├── tftp/
│   ├── autoexec.ipxe              # Entry: chains to HTTP
│   └── iPXE/
│       ├── ipxe.efi               # UEFI iPXE binary
│       └── undionly.kpxe          # Legacy BIOS iPXE binary
└── http/                          # Served by pxe-http.service on :8888
    ├── flatcar.ipxe               # Main boot script
    ├── flatcar-local.ipxe         # Identical backup copy
    ├── flatcar_production_pxe.vmlinuz
    ├── flatcar_production_pxe_image.cpio.gz
    └── karnataka-fresh.ign        # Ignition config
```


### Services on Bihar

**dnsmasq** (`/etc/dnsmasq.d/pxe.conf`):
```ini
interface=vmbr0
bind-interfaces
dhcp-range=192.168.0.10,192.168.0.254,12h
dhcp-option=3,192.168.0.1          # default gateway
dhcp-option=6,1.1.1.1,8.8.8.8     # DNS

# UEFI boot
dhcp-match=set:efi-x64,option:client-arch,7
dhcp-boot=tag:efi-x64,iPXE/ipxe.efi,192.168.0.5,192.168.0.5

# Legacy BIOS boot
dhcp-boot=tag:!efi-x64,iPXE/undionly.kpxe,192.168.0.5,192.168.0.5

# Static reservations
dhcp-host=9C:BF:0D:00:E5:0F,192.168.0.6,karnataka,12h
dhcp-host=D8:3A:DD:E9:C7:1D,192.168.0.10,raspberrypi,12h
dhcp-host=48:DA:35:6F:A9:20,192.168.0.99,kvm,12h
dhcp-host=A8:A1:59:E1:6D:84,192.168.0.5,bihar,12h

enable-tftp
tftp-root=/var/lib/pxe/tftp
```

**HTTP server** (`/etc/systemd/system/pxe-http.service`):
```ini
[Service]
WorkingDirectory=/var/lib/pxe/http
ExecStart=/usr/bin/python3 -m http.server 8888 --bind 0.0.0.0
User=www-data
```

> **Important:** `pxe-http.service` is **disabled** by default. You must start it manually before rebooting Karnataka and stop it afterwards.

```bash
# On Bihar, before rebooting Karnataka:
sudo systemctl start pxe-http.service

# After Karnataka is up and SSHable:
sudo systemctl stop pxe-http.service
```

---

## 5. Operating System: Flatcar Container Linux

### What is Flatcar?

Flatcar Container Linux is an immutable, container-optimized Linux distribution. The base OS is read-only. Extensions are added via **systemd-sysext** — squashfs images that overlay onto `/usr` at boot. There is no package manager.

### Current version

| Field         | Value                                    |
|--------------|------------------------------------------|
| **Version**  | 4593.2.1 (Oklo)                          |
| **Kernel**   | 6.12.87-flatcar                          |
| **Runtime**  | containerd 2.1.5                         |
| **Board**    | amd64-usr                                |

### Filesystem layout (diskless)

When running from PXE, the entire filesystem is in RAM:

```
tmpfs       32G   /          (root, writable)
sysext      32G   /usr       (read-only OS layer, loop-mounted)
overlay     32G   /etc       (writable overlay over /usr/etc)
tmpfs       13G   /run
tmpfs       32G   /tmp
```

**No disk partitions are mounted.** The NVMe drives are present (`nvme0n1`, `nvme1n1`) but unused.

### Systemd sysext extensions

Extensions are `.raw` squashfs images that extend `/usr`. They're downloaded at boot by Ignition and activated by `systemd-sysext.service`.

```
NAME               TYPE  PATH                              TIME
containerd-flatcar raw   /etc/extensions/containerd-flatcar.raw  (built-in)
docker-flatcar     raw   /etc/extensions/docker-flatcar.raw      (built-in)
kubernetes         raw   /etc/extensions/kubernetes.raw          (Ignition-downloaded)
tailscale          raw   /etc/extensions/tailscale.raw           (Ignition-downloaded)
```

To inspect active extensions:

```bash
systemd-sysext list
```

---

## 6. Ignition Configuration

Ignition is the first-boot provisioner for Flatcar. It runs before systemd, reading a JSON config fetched over HTTP. The config for Karnataka lives at:

```
/var/lib/pxe/http/karnataka-fresh.ign   (on Bihar)
```

### What Ignition provisions

#### Users

- `core` user
  - Groups: `sudo`, `docker`
  - 7 SSH authorized keys (ed25519) pre-loaded
  - Passwordless sudo via `/etc/sudoers.d/99-core-james`

#### Files written

| Path | Content |
|------|---------|
| `/etc/hostname` | `karnataka` |
| `/etc/systemd/network/20-dhcp.network` | DHCP on `enp191s0` (`[Match] Name=enp191s0`, `[Network] DHCP=yes`) |
| `/etc/sudoers.d/99-core-james` | `core ALL=(ALL) NOPASSWD: ALL` and `james ALL=(ALL) NOPASSWD: ALL` |
| `/etc/tailscale/tailscale.env` | `TS_AUTHKEY` + `TS_STATE_DIR=/var/lib/tailscale` |

#### Sysext downloads

| Extension | Version | Source |
|-----------|---------|--------|
| kubernetes | v1.33.2 | `https://extensions.flatcar.org/extensions/kubernetes-v1.33.2-x86-64.raw` |
| tailscale  | v1.98.3 | `https://github.com/flatcar/sysext-bakery/releases/download/tailscale-v1.98.3/tailscale-v1.98.3-x86-64.raw` |

Symlinks in `/etc/extensions/` activate them at runtime:
- `/etc/extensions/kubernetes.raw` → `/opt/extensions/kubernetes/kubernetes-v1.33.2-x86-64.raw`
- `/etc/extensions/tailscale.raw` → `/opt/extensions/tailscale/tailscale-v1.98.3-x86-64.raw`

#### Systemd units

| Unit | State | Purpose |
|------|-------|---------|
| `systemd-sysext.service` | enabled | Activates sysext images on boot |
| `systemd-sysupdate.timer` | enabled | Checks for OS updates periodically |
| `locksmithd.service` | **masked** | Disables Flatcar's automatic reboot-after-update lock daemon |
| `tailscale-oneshot.service` | enabled | Runs `tailscale up` once network is online |

### Editing the Ignition config

The config at `/var/lib/pxe/http/karnataka-fresh.ign` is raw Ignition JSON (spec 3.3.0). The recommended workflow is:

1. Write a human-readable **Butane** YAML config
2. Transpile to Ignition JSON:
   ```bash
   butane config.bu -o karnataka-fresh.ign
   ```
3. Validate:
   ```bash
   ignition-validate karnataka-fresh.ign
   ```
4. Replace the file in `/var/lib/pxe/http/` on Bihar

---

## 7. Kubernetes Cluster

### Overview

| Property              | Value                              |
|----------------------|------------------------------------|
| **Bootstrap tool**   | kubeadm                            |
| **Kubernetes**       | v1.33.2 (kubelet) / v1.33.12 (API server) |
| **CNI**              | Cilium                             |
| **Storage**          | local-path-provisioner (default SC) |
| **Topology**         | Single-node, control-plane only    |
| **Pod CIDR**         | `10.244.0.0/16`                    |
| **Service CIDR**     | `10.96.0.0/12`                     |
| **kube-proxy**       | disabled (Cilium handles it)       |

### Helm

Helm v3.21.0 is installed manually at `/home/core/bin/helm`. It is not in `$PATH` by default.

```bash
# Always invoke as:
/home/core/bin/helm <command>

# Or add to PATH for the session:
export PATH=/home/core/bin:$PATH
```

### Kubeconfig

The admin kubeconfig is at `~/.kube/config` (core user). It uses the `kind-kubeflex` context by default (set up by the KubeSteller init container).

```bash
kubectl config get-contexts
#   NAME           CLUSTER        AUTHINFO      NAMESPACE
#   its1           its1           its1
# * kind-kubeflex  kind-kubeflex  default-user  default
#   wds1           wds1           wds1
```

The `kind-kubeflex` context points at the main cluster API server (`https://10.96.0.1:443`). Use this for all general Kubernetes operations.

### Namespaces

| Namespace | Contents |
|-----------|----------|
| `kube-system` | Kubernetes control plane, Cilium, CoreDNS |
| `kubestellar` | KubeSteller UI (frontend, backend, postgres, redis) |
| `kubevirt` | KubeVirt operator and controllers |
| `kubeflex-system` | KubeFlex controller manager + PostgreSQL |
| `wds1-system` | KubeSteller controller manager + transport controller |
| `its1-system` | Inventory and Transport Space init jobs |
| `open-cluster-management` | OCM cluster manager |
| `open-cluster-management-hub` | OCM hub controllers (placement, registration, work, addon) |
| `tailscale` | Tailscale operator + ingress proxy pods |
| `local-path-storage` | local-path-provisioner |

---

## 8. KubeSteller Stack

### Architecture

KubeSteller is a multi-cluster workload management system. On this single-node deployment, both the **ITS** (Inventory and Transport Space) and **WDS** (Workload Description Space) use `type: host`, making them aliases for the same cluster. No vcluster or external networking is required.

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│                                                             │
│  ┌──────────────────────────────────┐                       │
│  │         KubeSteller UI           │  <- What you see      │
│  │   nginx (frontend) → backend API │                       │
│  │   PostgreSQL (user/policy DB)    │                       │
│  │   Redis (cache)                  │                       │
│  └─────────────┬────────────────────┘                       │
│                │ uses wds1 context                          │
│  ┌─────────────▼────────────────────┐                       │
│  │           wds1-system            │  <- KubeSteller core  │
│  │   kubestellar-controller-manager │                       │
│  │   transport-controller           │                       │
│  └─────────────┬────────────────────┘                       │
│                │ syncs via OCM                              │
│  ┌─────────────▼────────────────────┐                       │
│  │       open-cluster-management    │  <- OCM hub           │
│  │   cluster-manager                │                       │
│  │   placement / registration /     │                       │
│  │   work / addon controllers       │                       │
│  └──────────────────────────────────┘                       │
│                                                             │
│  ┌────────────────────┐                                     │
│  │   kubeflex-system  │  <- Control plane lifecycle mgmt    │
│  │   KubeFlex + PG    │                                     │
│  └────────────────────┘                                     │
└─────────────────────────────────────────────────────────────┘
```

### Components

#### KubeSteller UI (`kubestellar` namespace)

| Pod | Image | Purpose |
|-----|-------|---------|
| `frontend` | `ghcr.io/kubestellar/ui/frontend:v1.0.1` | React/nginx web UI |
| `backend` | `ghcr.io/kubestellar/ui/backend:latest` | Go API server (gin) |
| `postgresql` | `postgres:15-alpine` | User accounts, policy DB |
| `redis` | `ghcr.io/kubestellar/ui/redis:latest` | BindingPolicy cache |

**Access:**

| Path | URL |
|------|-----|
| Via Tailscale | `https://kubestellar.manatee-basking.ts.net` |
| Via LAN | `http://192.168.0.6:32224` |
| Status check | `GET /api/kubestellar/status` |

**Default credentials:** `admin` / `admin` — **change immediately after setup.**

#### KubeSteller Core (`wds1-system` namespace)

Installed via the `ks-core` Helm chart. Provides all `control.kubestellar.io` CRDs:

| CRD | Purpose |
|-----|---------|
| `bindingpolicies.control.kubestellar.io` | Route workloads to clusters |
| `bindings.control.kubestellar.io` | Resolved binding state |
| `combinedstatuses.control.kubestellar.io` | Aggregated workload status |
| `customtransforms.control.kubestellar.io` | Object transformation rules |
| `statuscollectors.control.kubestellar.io` | Status collection config |
| `workstatuses.control.kubestellar.io` | Per-cluster work status |

#### KubeFlex (`kubeflex-system` namespace)

KubeFlex manages the lifecycle of virtual control planes (ITS, WDS). With `type: host`, these are aliases to the hosting cluster itself.

| Pod | Purpose |
|-----|---------|
| `kubeflex-controller-manager` | Control plane lifecycle |
| `postgres-postgresql` | KubeFlex state persistence |

### Installation

```bash
/home/core/bin/helm upgrade --install ks-core \
  oci://ghcr.io/kubestellar/kubestellar/core-chart \
  --version 0.30.0 \
  --set-json='ITSes=[{"name":"its1","type":"host"}]' \
  --set-json='WDSes=[{"name":"wds1","type":"host"}]'
```

After all pods in `kubeflex-system`, `open-cluster-management`, `open-cluster-management-hub`, and `wds1-system` reach `Running`, restart the UI backend to re-run its init container and populate the WDS kubeconfig:

```bash
kubectl rollout restart deployment/backend -n kubestellar
```

### Known quirk: nginx-config namespace

The `nginx-config` ConfigMap in the `kubestellar` namespace sets the backend proxy address. It was originally misconfigured to point to `backend.default.svc.cluster.local` (wrong namespace). The correct value is:

```
backend.kubestellar.svc.cluster.local:4000
```

If the UI shows a "not connected" error and you see 502 responses in the browser, re-patch this ConfigMap and restart the frontend:

```bash
kubectl patch configmap nginx-config -n kubestellar --type=json \
  -p='[{"op":"replace","path":"/data/default.conf","value":"# corrected config here"}]'
kubectl rollout restart deployment/frontend -n kubestellar
```

---

## 9. KubeVirt

KubeVirt v1.8.2 allows running virtual machines as Kubernetes workloads.

| Component | Pods |
|-----------|------|
| `virt-operator` | 2 replicas — manages the KubeVirt installation |
| `virt-api` | 1 replica — REST API for VM operations |
| `virt-controller` | 2 replicas — reconciles VirtualMachine objects |
| `virt-handler` | 1 (daemonset) — runs on each node, interfaces with libvirt |

**Access:** `https://kubevirt.manatee-basking.ts.net` (Tailscale ingress)

**Status:**
```bash
kubectl get kubevirt -n kubevirt
# Should show Phase: Deployed
```

---

## 10. Tailscale Networking

### How it works

The **Tailscale Operator** (`tailscale` namespace) enables two things:

1. **Karnataka itself** joins the Tailscale network at boot via `tailscale-oneshot.service` (Ignition-managed)
2. **Kubernetes services** get Tailscale FQDNs via `Ingress` resources with `ingressClassName: tailscale`

### Auth key (Secure Workflow)

To prevent checking secrets into Git, the Tailscale auth key is retrieved dynamically from **Bitwarden** during the Ignition generation phase.

1. **Template**: `karnataka-fresh.bu.tmpl` contains a `{{TS_AUTHKEY}}` placeholder.
2. **Generation**: The `generate-ignition.sh` script:
   * Assumes the Bitwarden CLI is unlocked (`export BW_SESSION=$(bw unlock --raw)`).
   * Queries the `tailscale k8s operator` client secret from Bitwarden.
   * Substitutes the placeholder and transpiles it using Butane in a Podman container.
   * Directly writes the compiled, secret-filled `karnataka-fresh.ign` to `/var/lib/pxe/http/karnataka-fresh.ign` on **bihar** (where it is served to the network booting node).
   * Ensures the secret-filled Ignition file is completely ignored by Git via `.gitignore`.

To generate or regenerate the config, simply run:
```bash
./generate-ignition.sh
```

### Ingress resources

```yaml
# kubestellar-ui ingress
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: kubestellar-ui
  namespace: kubestellar
spec:
  ingressClassName: tailscale
  rules:
  - http:
      paths:
      - path: /
        backend:
          service:
            name: frontend
            port:
              number: 80
```

The Tailscale Operator creates a proxy pod (`ts-kubestellar-ui-*`) in the `tailscale` namespace for each ingress, assigning it a hostname on the tailnet.

---

## 11. Complete Reinstallation Guide

> Use this after a reboot, hardware reset, or fresh PXE rebuild. Follow steps in order.

### Phase 1: Boot the server

**On Bihar:**

```bash
# Start the PXE HTTP server
sudo systemctl start pxe-http.service

# Watch DHCP/TFTP to confirm Karnataka is booting
sudo journalctl -fu dnsmasq
```

**Trigger Karnataka to PXE boot** (power cycle or BIOS/UEFI network boot).

**Wait for Ignition to complete** — SSH becomes available when done:

```bash
# Poll until SSH responds (usually ~60–90 seconds)
until ssh -o ConnectTimeout=5 core@192.168.0.6 'echo ok' 2>/dev/null; do
  echo "Waiting..."; sleep 5
done

# Stop the HTTP server
sudo systemctl stop pxe-http.service
```

### Phase 2: Verify base provisioning

```bash
ssh core@192.168.0.6

# OS version
cat /etc/os-release | grep PRETTY_NAME
# → Flatcar Container Linux by Kinvolk 4593.2.1

# Sysexts loaded
systemd-sysext list
# → kubernetes and tailscale should appear

# Tailscale connected
tailscale status
# → Should show karnataka and the tailnet

# Kubernetes tools available
kubectl version --client
kubeadm version
```

### Phase 3: Initialize Kubernetes

```bash
ssh core@192.168.0.6

# Initialize the cluster
sudo kubeadm init \
  --pod-network-cidr=10.244.0.0/16 \
  --skip-phases=addon/kube-proxy

# Set up kubeconfig
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# Allow workloads on the control-plane node
kubectl taint nodes --all node-role.kubernetes.io/control-plane-
```

### Phase 4: Install Cilium CNI

```bash
/home/core/bin/helm repo add cilium https://helm.cilium.io/ 2>/dev/null || true
/home/core/bin/helm upgrade --install cilium cilium/cilium \
  --namespace kube-system \
  --set ipam.mode=kubernetes

# Wait for Cilium to be ready
kubectl -n kube-system rollout status daemonset/cilium
```

### Phase 5: Install local-path-provisioner

```bash
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml

# Verify default StorageClass
kubectl get sc
# → local-path (default)
```

### Phase 6: Install KubeSteller Core

```bash
/home/core/bin/helm upgrade --install ks-core \
  oci://ghcr.io/kubestellar/kubestellar/core-chart \
  --version 0.30.0 \
  --set-json='ITSes=[{"name":"its1","type":"host"}]' \
  --set-json='WDSes=[{"name":"wds1","type":"host"}]'

# Wait for all KubeSteller system pods
kubectl wait pod --for=condition=Ready \
  -n kubeflex-system --all --timeout=180s
kubectl wait pod --for=condition=Ready \
  -n open-cluster-management --all --timeout=180s
kubectl wait pod --for=condition=Ready \
  -n open-cluster-management-hub --all --timeout=180s
kubectl wait pod --for=condition=Ready \
  -n wds1-system --all --timeout=120s
```

### Phase 7: Install KubeSteller UI

> The UI manifests are consolidated in this repository at [kubestellar-ui-manifests.yaml](file:///home/james/dev/karnataka/kubestellar-ui-manifests.yaml). You can easily deploy the entire UI stack (frontend, backend, postgresql, and redis) using this file.

```bash
# 1. Create the namespace if needed
kubectl create namespace kubestellar --dry-run=client -o yaml | kubectl apply -f -

# 2. Deploy the consolidated UI manifests
kubectl apply -f /home/james/dev/karnataka/kubestellar-ui-manifests.yaml

# 3. Restart the backend to re-run the init container once KubeFlex is up
kubectl rollout restart deployment/backend -n kubestellar
kubectl rollout status deployment/backend -n kubestellar
```

> [!IMPORTANT]
> **Upstream Bug Patches (Post-deployment patches required for secure/clean login):**
> 1. **0-Cluster Dashboard Crash:** When there are `0` managed clusters in OCM, `/api/new/clusters` returns `{"clusters":null,"count":0}`. The frontend calls `.map()` on `r.data.clusters`, causing an uncaught React crash resulting in a **gray screen after login**.
> 2. **Insecure WebSocket (Mixed Content) Crash:** In secure HTTPS contexts (like Tailscale ingress), the frontend attempts to open a relative unencrypted WebSocket (`ws:///ws/namespaces`), which the browser blocks as a mixed-content security violation, throwing `DOMException: The operation is insecure`.
> 
> To apply both patches, you can run the helper script in the repository from **Bihar** (since it utilizes Bihar's Python 3 to modify the assets safely in the container):
> ```bash
> # Run the WebSocket & cluster query patches from Bihar:
> bash /home/james/dev/karnataka/patch-websocket.sh
> ```
> 
> Alternatively, you can apply them manually inside the running frontend pod:
> ```bash
> # 1. Patch the 0-cluster map crash:
> kubectl exec deployment/frontend -n kubestellar -- sed -i 's/r.data.clusters.map/(r.data.clusters||\[\]).map/g' /usr/share/nginx/html/assets/useClusterQueries-C4i67ZwO.js
> 
> # 2. Patch the relative ws:// connection to dynamically use window.location protocol/host:
> kubectl exec deployment/frontend -n kubestellar -- sed -i 's#const Ss=e=>{const t="",r=t.startsWith("https")?"wss":"ws",o=t.replace(/^https?:\/\//,"");return#const Ss=e=>{const t="",r=window.location.protocol==="https:"?"wss":"ws",o=window.location.host;return#g' /usr/share/nginx/html/assets/index-BUr-cMfJ.js
> ```



**Verify the connection:**

```bash
TOKEN=$(curl -s -X POST http://192.168.0.6:32224/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' \
  | grep -o '"token":"[^"]*"' | cut -d: -f2 | tr -d '"')

curl -s http://192.168.0.6:32224/api/kubestellar/status \
  -H "Authorization: Bearer $TOKEN"
# → {"allReady":true,...}
```

### Phase 8: Install KubeVirt

```bash
# Get latest stable version
export KUBEVIRT_VERSION=$(curl -s https://storage.googleapis.com/kubevirt-prow/release/kubevirt/kubevirt/stable.txt)
# Or pin to known-good: export KUBEVIRT_VERSION=v1.8.2

kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-cr.yaml

# Wait for deployment
kubectl wait kubevirt kubevirt -n kubevirt \
  --for=condition=Available --timeout=300s
```

### Phase 9: Install Tailscale Operator

```bash
/home/core/bin/helm upgrade --install tailscale-operator \
  oci://ghcr.io/tailscale/helm-charts/tailscale-operator \
  --namespace tailscale \
  --create-namespace \
  --set-string oauth.clientId="<TS_CLIENT_ID>" \
  --set-string oauth.clientSecret="<TS_CLIENT_SECRET>"
```

After the operator is running, re-apply the Ingress resources for KubeSteller UI and KubeVirt API.

### Post-install checklist

```bash
# All pods healthy?
kubectl get pods --all-namespaces | grep -v -E "Running|Completed"
# → Should only show: cilium-operator (1/2, expected on single-node)

# KubeSteller UI accessible?
curl -s https://kubestellar.manatee-basking.ts.net/api/kubestellar/status \
  -H "Authorization: Bearer $TOKEN" | grep allReady
# → "allReady":true

# KubeVirt deployed?
kubectl get kubevirt -n kubevirt
# → Phase: Deployed

# Storage working?
kubectl get sc
# → local-path (default)
```

---

## 12. Troubleshooting

### Karnataka doesn't PXE boot

1. Confirm `pxe-http.service` is running on Bihar: `sudo systemctl status pxe-http.service`
2. Check dnsmasq is running: `sudo systemctl status dnsmasq`
3. Watch DHCP/TFTP in real time: `sudo journalctl -fu dnsmasq`
4. Confirm Karnataka's MAC is `9C:BF:0D:00:E5:0F` — check `/etc/dnsmasq.d/pxe.conf`
5. Confirm the BIOS/UEFI is set to PXE/network boot

### SSH not available after boot

- Ignition may still be running (downloading sysexts takes time on first boot)
- Check the serial console if available — Ignition logs appear there
- Ignition failure will drop to emergency shell; check `/run/ignition.json` and journal

### Sysext not activating

```bash
systemctl status systemd-sysext.service
journalctl -u systemd-sysext.service
# Extensions must be valid squashfs with correct metadata
```

### Kubernetes CrashLoopBackOff / pods stuck

```bash
# Get pod events
kubectl describe pod <pod-name> -n <namespace>

# Check logs including previous crashes
kubectl logs <pod-name> -n <namespace> --previous
```

### KubeSteller UI shows "not connected" / 502 errors

The nginx proxy in the frontend pod may be pointing to the wrong backend namespace.

```bash
# Check current nginx config
kubectl exec -n kubestellar deployment/frontend \
  -- cat /etc/nginx/conf.d/default.conf | grep backend

# Should show: backend.kubestellar.svc.cluster.local:4000
# If it shows: backend.default.svc.cluster.local:4000  ← wrong!
```

Fix:
```bash
kubectl get configmap nginx-config -n kubestellar -o yaml \
  | sed 's/backend.default.svc/backend.kubestellar.svc/g' \
  | kubectl apply -f -
kubectl rollout restart deployment/frontend -n kubestellar
```

### KubeSteller backend errors about missing CRDs

```
failed to list binding policies: the server could not find the requested resource
(get bindingpolicies.control.kubestellar.io)
```

The KubeSteller core chart (`ks-core`) has not been installed, or was installed after the backend started. Run Phase 6 from the reinstallation guide, then restart the backend:

```bash
kubectl rollout restart deployment/backend -n kubestellar
```

### Cilium operator has 1 pod Pending

This is expected on a single-node cluster. The `cilium-operator` Deployment requests 2 replicas but there is only 1 node. One pod will always be `Pending`. This does not affect cluster operation — one replica is sufficient.

### Cannot schedule pods / NoSchedule taint

After `kubeadm init`, the control-plane node has a `NoSchedule` taint. Remove it:

```bash
kubectl taint nodes --all node-role.kubernetes.io/control-plane-
```

---

## Quick Reference Card

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 KARNATAKA · QUICK REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 SSH
   ssh core@192.168.0.6
   ssh core@karnataka.manatee-basking.ts.net

 SERVICES
   KubeSteller UI    https://kubestellar.manatee-basking.ts.net
                     http://192.168.0.6:32224
   KubeVirt API      https://kubevirt.manatee-basking.ts.net

 PXE BOOT (run on Bihar before rebooting Karnataka)
   sudo systemctl start pxe-http.service
   sudo journalctl -fu dnsmasq   # watch DHCP/TFTP

 KUBERNETES
   kubectl get pods --all-namespaces
   kubectl get nodes -o wide
   /home/core/bin/helm ...    # helm is not in $PATH

 KUBESTELLAR STATUS CHECK
   TOKEN=$(curl -s -X POST http://192.168.0.6:32224/login \
     -H 'Content-Type: application/json' \
     -d '{"username":"admin","password":"admin"}' \
     | grep -o '"token":"[^"]*"' | cut -d: -f2 | tr -d '"')
   curl -s http://192.168.0.6:32224/api/kubestellar/status \
     -H "Authorization: Bearer $TOKEN"

 SYSEXTS
   systemd-sysext list

---

## 13. vLLM ROCm Local LLM Setup

To run a high-throughput, OpenAI-compatible local LLM on the **Ryzen AI MAX+ 395 (Strix Halo) GPU** inside Kubernetes, we use **vLLM** with ROCm acceleration.

### Overview

1. **Architecture**: Strix Halo features a powerful Radeon 8060S GPU (`gfx1151`) with 62 GB of shared unified memory.
2. **GPU Passthrough**: Requires the host OS to load the `amdgpu` driver (enabling `/dev/kfd` and `/dev/dri`). Since the default Flatcar kernel compiles graphics out, you must boot an OS that loads `amdgpu` or compile it manually.
3. **GFX Compatibility**: Since `gfx1151` is not natively supported by ROCm out of the box, we inject `HSA_OVERRIDE_GFX_VERSION=11.0.2` into the container environment to force RDNA3 compatibility.
4. **Tailnet Ingress**: Exposes the OpenAI-compatible API at `http://vllm.manatee-basking.ts.net`.

### Deployment

To deploy vLLM ROCm, simply execute the helper script:
```bash
./vllm/deploy.sh
```

This applies the following manifests in sequence:
* `vllm/00-namespace.yaml`: Creates the `vllm` namespace.
* `vllm/01-pvc.yaml`: Declares a 16Gi cache volume for HuggingFace model weights.
* `vllm/02-deployment-rocm.yaml`: Launches the `vllm/vllm-openai:latest-rocm` image, configured with `HSA_OVERRIDE_GFX_VERSION=11.0.2`, direct rendering privileges, and requests `amd.com/gpu: "1"`. It loads `Qwen/Qwen2.5-Coder-7B-Instruct` by default.
* `vllm/03-service.yaml`: Declares a ClusterIP service on port 8000.
* `vllm/04-ingress.yaml`: Exposes the service securely over Tailscale Ingress.

### Verification

1. Verify the pod is running:
   ```bash
   ssh core@192.168.0.6 "kubectl get pods -n vllm"
   ```
2. Test the OpenAI-compatible endpoint from your Tailnet:
   ```bash
   curl http://vllm.manatee-basking.ts.net/v1/models
   ```
3. Run inference via standard OpenAI client or curl:
   ```bash
   curl http://vllm.manatee-basking.ts.net/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
       "messages": [{"role": "user", "content": "Write a python script to check Kubernetes pod health."}]
     }'
   ```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
