# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This repository documents the configuration, setup procedures, and operational knowledge for **karnataka**, a Flatcar Container Linux server at `192.168.0.6`. The server runs entirely in RAM (PXE netboot, diskless) — **all state is lost on reboot** and must be re-provisioned via Ignition + manual steps. The primary goal is to store everything needed to reproduce the server from scratch.

Current first project: get **KubeSteller** fully working.

---

## Hardware

| Component | Details |
|-----------|---------|
| CPU | AMD Ryzen AI MAX+ 395 (Strix Halo), 16 cores / 32 threads, up to 5.185 GHz |
| RAM | 62 GB |
| GPU | AMD Radeon 8060S (integrated, Strix Halo) |
| NIC | Realtek RTL8126 5GbE (`enp191s0`), MAC `9C:BF:0D:00:E5:0F` |
| WiFi | MediaTek MT7925 Wi-Fi 7 |
| NVMe 0 | WD Black SN850X 931.5 GB (`nvme0n1`) — has a Flatcar partition layout, currently unused |
| NVMe 1 | Micron 2550 931.5 GB (`nvme1n1`) — single partition, currently unused |
| USB sda | 114.6 GB with Flatcar partition layout (likely a previous install medium) |

The NVMe drives are **not mounted** in the current netboot configuration. The entire OS and Kubernetes state live in RAM.

---

## Network

| Host | IP | MAC | Notes |
|------|----|-----|-------|
| karnataka | `192.168.0.6` | `9C:BF:0D:00:E5:0F` | This server |
| bihar | `192.168.0.5` | `A8:A1:59:E1:6D:84` | PXE server / homelab host (Proxmox) |
| raspberrypi | `192.168.0.10` | `D8:3A:DD:E9:C7:1D` | — |
| kvm | `192.168.0.99` | `48:DA:35:6F:A9:20` | KVM host |

DHCP range: `192.168.0.10–254` (dnsmasq on `bihar:vmbr0`)  
Tailscale network: `manatee-basking.ts.net`  
Tailscale hostname: `karnataka.manatee-basking.ts.net`

---

## OS

| Field | Value |
|-------|-------|
| OS | Flatcar Container Linux 4593.2.1 (Oklo) |
| Kernel | 6.12.87-flatcar |
| Container runtime | containerd 2.1.5 |
| Boot method | PXE (iPXE) — fully diskless, runs in RAM |
| Login user | `core` (also `james` via Tailscale/SSH) |

SSH: `ssh core@192.168.0.6` or `ssh core@karnataka.manatee-basking.ts.net`

---

## PXE Boot Infrastructure (on bihar)

All files live on **bihar** (`192.168.0.5`). The boot chain:

```
DHCP (dnsmasq) → TFTP autoexec.ipxe → HTTP flatcar.ipxe → Flatcar kernel + Ignition
```

### File locations on bihar (Consolidated in Repository)

| System Path | Repository File | Purpose |
|-------------|-----------------|---------|
| `/etc/dnsmasq.d/pxe.conf` | [dnsmasq-pxe.conf](file:///home/james/dev/karnataka/dnsmasq-pxe.conf) | DHCP + TFTP config (interface: `vmbr0`) |
| `/var/lib/pxe/tftp/autoexec.ipxe` | [autoexec.ipxe](file:///home/james/dev/karnataka/autoexec.ipxe) | Entry iPXE script; chains to HTTP server |
| `/var/lib/pxe/tftp/iPXE/ipxe.efi` | — | UEFI iPXE binary |
| `/var/lib/pxe/tftp/iPXE/undionly.kpxe` | — | Legacy BIOS iPXE binary |
| `/var/lib/pxe/http/flatcar.ipxe` | [flatcar.ipxe](file:///home/james/dev/karnataka/flatcar.ipxe) | Main iPXE boot script |
| `/var/lib/pxe/http/flatcar_production_pxe.vmlinuz` | — | Flatcar kernel |
| `/var/lib/pxe/http/flatcar_production_pxe_image.cpio.gz` | — | Flatcar initramfs |
| `/var/lib/pxe/http/karnataka-fresh.ign` | [karnataka-fresh.ign](file:///home/james/dev/karnataka/karnataka-fresh.ign) / [karnataka-fresh.bu](file:///home/james/dev/karnataka/karnataka-fresh.bu) | Ignition JSON & Butane source config |
| `/etc/systemd/system/pxe-http.service` | — | systemd unit: `python3 -m http.server 8888` serving `/var/lib/pxe/http` |


### Starting the HTTP server (required before rebooting karnataka)

```bash
sudo systemctl start pxe-http.service
# The service is disabled by default; start it manually when needed
# Stop it after karnataka has booted successfully
sudo systemctl stop pxe-http.service
```

### flatcar.ipxe (current content)

```ipxe
#!ipxe
set base-url http://192.168.0.5:8888
kernel ${base-url}/flatcar_production_pxe.vmlinuz initrd=flatcar_production_pxe_image.cpio.gz flatcar.first_boot=1 ignition.config.url=http://192.168.0.5:8888/karnataka-fresh.ign
initrd ${base-url}/flatcar_production_pxe_image.cpio.gz
boot
```

---

## Ignition Config (`karnataka-fresh.ign`)

The Ignition config at `/var/lib/pxe/http/karnataka-fresh.ign` provisions the following on every fresh boot:

### Users
- `core` user, groups: `sudo`, `docker`
- 7 SSH authorized keys (ed25519) pre-loaded

### Systemd sysext extensions (downloaded at boot)
| Extension | Source |
|-----------|--------|
| `kubernetes-v1.33.2-x86-64.raw` | `https://extensions.flatcar.org/extensions/` |
| `tailscale-v1.98.3-x86-64.raw` | GitHub: `flatcar/sysext-bakery` |

Extensions are symlinked into `/etc/extensions/` and activated by `systemd-sysext.service`.

Built-in sysexts also present: `containerd-flatcar`, `docker-flatcar`.

### Files written
| Path | Content |
|------|---------|
| `/etc/hostname` | `karnataka` |
| `/etc/systemd/network/20-dhcp.network` | DHCP on `enp191s0` |
| `/etc/sudoers.d/99-core-james` | `core` and `james` get `NOPASSWD: ALL` |
| `/etc/tailscale/tailscale.env` | `TS_AUTHKEY` and `TS_STATE_DIR=/var/lib/tailscale` |

### Systemd units
| Unit | State |
|------|-------|
| `systemd-sysext.service` | enabled |
| `systemd-sysupdate.timer` | enabled |
| `locksmithd.service` | masked (Flatcar auto-update locksmith) |
| `tailscale-oneshot.service` | enabled — runs `tailscale up` after network comes up |

---

## Kubernetes Setup

Kubernetes is **not set up by Ignition** — it must be initialized manually after each boot. The `kubernetes` sysext installs `kubectl`, `kubeadm`, and `kubelet` into `/usr/local/bin`.

### Current cluster state

| Field | Value |
|-------|-------|
| Version | v1.33.2 (kubelet) / v1.33.12 (API server) |
| Bootstrap tool | kubeadm |
| Topology | Single-node, control-plane only |
| Pod CIDR | `10.244.0.0/16` |
| Service CIDR | `10.96.0.0/12` |
| kube-proxy | disabled |
| CNI | Cilium |
| Storage provisioner | local-path-provisioner |

### kubeadm init command (to reproduce)

```bash
sudo kubeadm init \
  --pod-network-cidr=10.244.0.0/16 \
  --skip-phases=addon/kube-proxy
```

Then copy kubeconfig:
```bash
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

Untaint control-plane so pods schedule:
```bash
kubectl taint nodes --all node-role.kubernetes.io/control-plane-
```

### Install Cilium CNI

```bash
helm repo add cilium https://helm.cilium.io/
helm install cilium cilium/cilium --namespace kube-system
```

### Install local-path-provisioner

```bash
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml
```

### Install KubeSteller core + KubeFlex (v0.30.0)

Helm is at `/home/core/bin/helm` (not in PATH by default).

```bash
/home/core/bin/helm upgrade --install ks-core \
  oci://ghcr.io/kubestellar/kubestellar/core-chart \
  --version 0.30.0 \
  --set-json='ITSes=[{"name":"its1","type":"host"}]' \
  --set-json='WDSes=[{"name":"wds1","type":"host"}]'
```

`type: host` means both ITS and WDS are aliases for the same cluster (no vcluster, no multi-cluster networking needed). The chart automatically installs KubeFlex + PostgreSQL into `kubeflex-system`.

After the chart deploys, wait for all pods in `kubeflex-system`, `open-cluster-management`, `open-cluster-management-hub`, and `wds1-system` to be Running, then restart the KubeSteller UI backend so its init container re-runs and populates the WDS1 kubeconfig:

```bash
kubectl rollout restart deployment/backend -n kubestellar
```

CRDs installed by this chart: `bindingpolicies.control.kubestellar.io`, `bindings`, `combinedstatuses`, `customtransforms`, `statuscollectors`, `workstatuses` (all under `control.kubestellar.io`), plus `controlplanes.tenancy.kflex.kubestellar.org`.

---

## Running Workloads

### `kubestellar` namespace — KubeSteller UI

| Component | Image | Exposure |
|-----------|-------|----------|
| frontend | `ghcr.io/kubestellar/ui/frontend:v1.0.1` | NodePort 32224 + Tailscale ingress |
| backend | `ghcr.io/kubestellar/ui/backend:latest` | ClusterIP 4000 |
| postgresql | `postgres:15-alpine` | ClusterIP 5432 |
| redis | `ghcr.io/kubestellar/ui/redis:latest` | ClusterIP 6379 |

Access: `https://kubestellar.manatee-basking.ts.net` (Tailscale) or `http://192.168.0.6:32224`

### `kubevirt` namespace — KubeVirt v1.8.2

Virtual machine management in Kubernetes. Tailscale ingress at `kubevirt.manatee-basking.ts.net`.

### `tailscale` namespace — Tailscale Operator

Provides Tailscale-based Ingress resources for `kubestellar-ui` and `kubevirt-api`.

### `kubeflex-system` namespace — KubeFlex

KubeFlex controller manager + PostgreSQL. Manages the ITS and WDS control plane lifecycle.

### `open-cluster-management` + `open-cluster-management-hub` — OCM

Open Cluster Management hub controllers (placement, registration, work, addon). Installed automatically by the KubeSteller core chart.

### `wds1-system` — WDS1 (Workload Description Space)

KubeSteller controller manager + transport controller. This is the `wds1` context that the UI backend connects to for reading/writing `BindingPolicy` resources.

### `its1-system` — ITS1 (Inventory and Transport Space)

Hub for cluster inventory. Completed init jobs live here.

---

## Reinstallation Checklist

When karnataka is rebooted (state is wiped), the full setup sequence is:

1. Start PXE HTTP server on bihar: `sudo systemctl start pxe-http.service`
2. Boot karnataka (PXE boot happens automatically via DHCP)
3. Wait for Ignition to complete — SSH becomes available at `core@192.168.0.6`
4. Stop PXE HTTP server on bihar: `sudo systemctl stop pxe-http.service`
5. Verify sysexts: `systemd-sysext list` (should show `kubernetes` and `tailscale`)
6. Verify Tailscale: `tailscale status`
7. Initialize Kubernetes (see kubeadm section above)
8. Install Cilium CNI
9. Install local-path-provisioner
10. Install KubeSteller core chart v0.30.0 (see KubeSteller section above)
11. Wait for KubeFlex, OCM, and WDS1 pods to be Running
12. Deploy KubeStellar UI from consolidated manifests: `kubectl apply -f kubestellar-ui-manifests.yaml`
13. Restart the backend deployment and patch the frontend UI: `bash patch-websocket.sh`
14. Deploy KubeVirt, Tailscale operator
15. Configure Tailscale Ingress resources

---

## Modifying the Ignition Config

Edit `/var/lib/pxe/http/karnataka-fresh.ign` on **bihar**. The file is raw JSON (Ignition spec 3.3.0). To make changes:

- Use [Butane](https://coreos.github.io/butane/) to author in YAML then transpile to Ignition JSON: `butane config.bu -o karnataka-fresh.ign`
- Or edit the JSON directly and validate with `ignition-validate karnataka-fresh.ign`

To update sysext versions, update the `source` URLs and symlink targets in the `storage.files` and `storage.links` sections.

---

## Useful Commands

```bash
# On karnataka
kubectl get all --all-namespaces
kubectl get nodes -o wide
systemd-sysext list
tailscale status

# On bihar — check/start PXE server
sudo systemctl status pxe-http.service
sudo systemctl start pxe-http.service

# On bihar — watch dnsmasq DHCP/TFTP (useful during PXE boot)
sudo journalctl -fu dnsmasq

# SSH into karnataka
ssh core@192.168.0.6
ssh core@karnataka.manatee-basking.ts.net
```
