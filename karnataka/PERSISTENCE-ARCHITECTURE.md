# Persistence Architecture - Diskless Flatcar K8s Cluster

This document outlines the architectural strategy to maintain complete Kubernetes cluster state, container runtimes, and workload persistent storage across reboots on diskless Flatcar Container Linux nodes netbooting via PXE. 

It also includes the multi-node roadmap for transitioning the PXE server to a Raspberry Pi and adding **Bihar** as a second Flatcar worker/control-plane node.

---

## 1. The Core Challenge

By default, network-booted Flatcar Container Linux runs entirely in RAM (`tmpfs`). 
* **State Loss**: A reboot wipes the entire operating system state, including `/etc/kubernetes` (certificates, kubeconfig), `/var/lib/kubelet` (pod states, mount bindings), and `/var/lib/etcd` (the core cluster database).
* **Storage Loss**: Local storage provisioners backed by RAM-mounted folders wipe all database and workload data.

---

## 2. The Persistence Architecture

To solve this, we leverage the **local physical NVMe drives** (`nvme0n1` and `nvme1n1`) which are physically present on the nodes but currently unused. By partition-mounting these drives and symlinking Kubernetes system directories, we achieve persistent state under an ephemeral OS.

```
┌────────────────────────────────────────────────────────┐
│                   DISKLESS FLATCAR OS                 │
│              Netboots to RAM via iPXE/HTTP             │
└───────┬───────────────────┬───────────────────┬────────┘
        │                   │                   │
        │ symlink           │ symlink           │ symlink
        ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌───────────────┐
│/etc/kubern...│    │/var/lib/kubelet    │/var/lib/etcd  │
└───────┬──────┘    └───────┬──────┘    └───────┬───────┘
        │                   │                   │
        └─────────────┐     │     ┌─────────────┘
                      ▼     ▼     ▼
┌────────────────────────────────────────────────────────┐
│                   PERSISTENT NVME MOUNT                │
│             /var/lib/state (/dev/nvme0n1p1)            │
└────────────────────────────────────────────────────────┘
```

### Step A: Ignition-Managed Persistent Disk Mount
We format and mount the local NVMe drive to `/var/lib/state` during the early boot phase before the container runtime or Kubelet services start.

We add this to the Butane configuration (`karnataka-fresh.bu.tmpl`):
```yaml
storage:
  disks:
    - device: /dev/nvme0n1
      wipe_table: false # Set to true on very first install
      partitions:
        - number: 1
          label: state
  filesystems:
    - device: /dev/disk/by-partlabel/state
      format: ext4
      path: /var/lib/state
      wipe_filesystem: false # Keep false to prevent wiping state on reboots!
```

### Step B: System Directory Redirects (Symlinks)
To ensure Kubernetes writes all configuration and database state to the NVMe partition, we create persistent symlinks in Butane:

```yaml
storage:
  links:
    - path: /etc/kubernetes
      target: /var/lib/state/etc-kubernetes
    - path: /var/lib/kubelet
      target: /var/lib/state/kubelet
    - path: /var/lib/etcd
      target: /var/lib/state/etcd
    - path: /var/lib/containerd
      target: /var/lib/state/containerd # Optional: persists container image cache
```

### Step C: Boot-Time Initialization Logic
We configure early-boot systemd units to handle the difference between the **First Boot** (where no state exists on the NVMe) and **Subsequent Boots** (where Kubelet should resume using the existing state):

1. **Directories Setup**: An early `oneshot` service creates the target directories on the mounted NVMe if they do not exist:
   ```bash
   mkdir -p /var/lib/state/etc-kubernetes /var/lib/state/kubelet /var/lib/state/etcd /var/lib/state/containerd
   ```
2. **Resuming K8s**:
   * **First Boot**: You log in and run `kubeadm init`. It writes the database to `/var/lib/etcd` (resolved to NVMe) and configs to `/etc/kubernetes` (resolved to NVMe).
   * **Reboot**: On boot, Ignition mounts the NVMe, symlinks the folders, and the standard Kubelet service starts. Kubelet reads `/var/lib/state/etc-kubernetes` and `/var/lib/state/kubelet` and **seamlessly resumes the cluster without re-initialization**.

---

## 3. Workload Storage: Distributed High-Availability (Longhorn)

Once we have local persistent partitions mounted on the nodes, we can deploy **Longhorn** (Rancher's CNCF storage engine, which is the storage core of Harvester):

* **How it works**: Longhorn runs as a DaemonSet across the cluster, consuming directories under `/var/lib/state/storage/` on each node's local NVMe.
* **Resilience**: It replicates Virtual Machine disks and database volumes across both **Karnataka** and **Bihar**.
* **High Availability**: If **Karnataka** reboots, the virtual machines can be rescheduled onto **Bihar**, mounting the exact same replicated volume from Bihar's NVMe over the network. Zero data loss, near-zero downtime.

---

## 4. Multi-Node Roadmap: Relocating the PXE Server

To free up **Bihar** (`192.168.0.5`) to act as a second Flatcar node, we relocate the PXE boot infrastructure to a **Raspberry Pi**:

```
┌────────────────────────────────────────────────────────┐
│                   RASPBERRY PI                         │
│               IP: 192.168.0.4 (Static)                 │
│         dnsmasq (DHCP/TFTP) + python3 (HTTP Server)    │
└───────────────┬────────────────────────┬───────────────┘
                │                        │
                │ iPXE Boot Chain        │ iPXE Boot Chain
                ▼                        ▼
┌────────────────────────┐      ┌────────────────────────┐
│       KARNATAKA        │      │         BIHAR          │
│      192.168.0.6       │      │      192.168.0.5       │
│   Flatcar K8s Node 1   │      │   Flatcar K8s Node 2   │
└────────────────────────┘      └────────────────────────┘
```

### Transition Steps:

1. **Set Up the Pi**:
   * Install a minimal OS (e.g. Raspberry Pi OS Lite).
   * Assign it a static IP (e.g. `192.168.0.4`).
   * Install `dnsmasq` and copy the configuration from [dnsmasq-pxe.conf](file:///home/james/dotfiles/karnataka/dnsmasq-pxe.conf).
2. **Move PXE Boot Files**:
   * Copy the boot files from Bihar `/var/lib/pxe/` to the Pi (e.g. `/var/lib/pxe/`).
   * Set up the systemd unit `pxe-http.service` on the Pi to serve files on port `8888`.
3. **Update iPXE Scripts**:
   * Edit `flatcar.ipxe` and `autoexec.ipxe` on the Pi to point to the Pi's IP:
     ```ipxe
     #!ipxe
     set base-url http://192.168.0.4:8888
     kernel ${base-url}/flatcar_production_pxe.vmlinuz initrd=flatcar_production_pxe_image.cpio.gz flatcar.first_boot=1 ignition.config.url=http://192.168.0.4:8888/karnataka-fresh.ign
     ```
4. **Reprovision Bihar**:
   * Update `dnsmasq-pxe.conf` on the Pi to add a DHCP lease reservation for Bihar's MAC address `A8:A1:59:E1:6D:84` to boot into Flatcar.
   * Boot Bihar via network PXE! It will load Flatcar into RAM and join Karnataka as a second node in your HA Kubernetes cluster.
