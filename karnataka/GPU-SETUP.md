# GPU Acceleration Setup Guide - AMD Strix Halo on Flatcar Container Linux

This guide details the architecture, automated build pipeline, and system configurations used to enable, load, and persist the **AMDGPU kernel driver** and **Strix Halo (RDNA3.5) GPU firmware** on network-booted Flatcar Container Linux nodes, bridging them to **Kubernetes** to run high-throughput LLMs via **vLLM ROCm**.

---

## 1. The Core Architecture

By default, Flatcar Container Linux is minimal, immutable, and compiles out the `amdgpu` driver in its kernel configuration (`CONFIG_DRM_AMDGPU is not set`). 

To run hardware-accelerated workloads on your **Ryzen AI MAX+ 395 (Strix Halo) GPU** (with a massive **64 GB of unified VRAM**), we employ the following three-part architecture:

```
┌─────────────────────────────────────────────────────────────────┐
│                    DISKLESS FLATCAR OS (RAM)                    │
│                      Read-Only Root Filesystem                  │
└───────────────┬─────────────────────────┬───────────────────────┘
                │                         │
                │ overlayfs               │ overlayfs
                ▼                         ▼
   ┌────────────────────────┐┌────────────────────────┐
   │    /usr/lib/modules    ││   /usr/lib/firmware    │
   └────────────┬───────────┘└────────────┬───────────┘
                │                         │
                ▼                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PERSISTENT NVME DRIVE MOUNT                  │
│                     /var/lib/state/ (/dev/nvme0n1p1)            │
└───────────────┬─────────────────────────┬───────────────────────┘
                │                         │
                ▼                         ▼
   ┌────────────────────────┐┌────────────────────────┐
   │ /var/lib/state/modules ││/var/lib/state/firmware │
   │   (Custom amdgpu.ko)   ││   (gfx1151*.bin blobs) │
   └────────────────────────┘└────────────────────────┘
```

1. **Host-Side Overlayfs Mounts**:
   Since the OS folders `/usr/lib/modules` and `/usr/lib/firmware` are read-only, systemd `overlay` units are executed early in the boot sequence to merge them with persistent folders on the local NVMe drive `/var/lib/state/modules` and `/var/lib/state/firmware`.
2. **Dynamic Modprobe loading**:
   A configuration file `/etc/modules-load.d/amdgpu.conf` ensures that the host kernel automatically loads the compiled module during boot.
3. **Kubernetes Device Mapping**:
   The **AMD GPU Device Plugin** is deployed as a DaemonSet in Kubernetes to scan `/dev/kfd` and `/dev/dri`, exposing `amd.com/gpu: "1"` as an allocatable resource for the cluster scheduler.

---

## 2. Automated Compilation & Deployment

We compile the `amdgpu.ko` module and its helper dependencies entirely in isolation on **Bihar** using a containerized Flatcar Developer SDK. This guarantees the compiled modules match the exact kernel version (`6.12.87-flatcar`) running on the target node.

### Quick Start: Building & Deploying the Driver
To build the driver modules, download the Strix Halo firmware blobs, and deploy them directly to your cluster, run:
```bash
bash /home/james/dotfiles/karnataka/build-amdgpu.sh
```

### Under the Hood: The Build Script Workflow
1. **Config Extraction**: Fetches Karnataka's active `/proc/config.gz` over SSH.
2. **Firmware Pull**: Connects to `kernel.org`'s `linux-firmware` git tree and pulls all `gfx1151` RDNA3.5 firmware blobs (MEC, SDMA, VCN, etc.) and `psp_14` security engine binaries.
3. **Podman Builder**: Spawns the official Flatcar Developer Container corresponding to version `6.12.87`.
4. **Kernel compilation**:
   * Downloads kernel source trees.
   * Modifies `.config` to set `CONFIG_DRM_AMDGPU=m` and dependencies.
   * Compiles drivers under `drivers/gpu/drm` using `-j$(nproc)`.
5. **Compression & Transfer**: Compresses the `.ko` files to matching `.ko.xz`, uploads them directly into Karnataka's NVMe folders over `scp`, and executes a remote `depmod` to map the dependencies.
6. **Ignition Regeneration**: Automatically recompiles Butane OS templates into secure boot-time Ignition configurations.

---

## 3. Host OS Config Details (`karnataka-fresh.bu.tmpl`)

The systemd units compiled into the Butane template to manage overlays are defined as follows:

```yaml
systemd:
  units:
    # Early oneshot to create directories on the NVMe before mount attempts
    - name: prepare-overlay-dirs.service
      enabled: true
      contents: |
        [Unit]
        Description=Prepare Writable Overlay Directories
        Requires=var-lib-state.mount
        After=var-lib-state.mount
        Before=usr-lib-modules.mount usr-lib-firmware.mount
        [Service]
        Type=oneshot
        ExecStart=/usr/bin/mkdir -p /var/lib/state/modules /var/lib/state/modules_work /var/lib/state/firmware /var/lib/state/firmware_work
        RemainAfterExit=yes
        [Install]
        WantedBy=multi-user.target

    # Writable modules overlay mount
    - name: usr-lib-modules.mount
      enabled: true
      contents: |
        [Unit]
        Description=Overlay for Writable Kernel Modules
        Requires=var-lib-state.mount prepare-overlay-dirs.service
        After=prepare-overlay-dirs.service
        Before=systemd-modules-load.service
        [Mount]
        What=overlay
        Where=/usr/lib/modules
        Type=overlay
        Options=lowerdir=/usr/lib/modules,upperdir=/var/lib/state/modules,workdir=/var/lib/state/modules_work
        [Install]
        WantedBy=multi-user.target

    # Writable firmware overlay mount
    - name: usr-lib-firmware.mount
      enabled: true
      contents: |
        [Unit]
        Description=Overlay for Writable Firmware
        Requires=var-lib-state.mount prepare-overlay-dirs.service
        After=prepare-overlay-dirs.service
        Before=systemd-modules-load.service
        [Mount]
        What=overlay
        Where=/usr/lib/firmware
        Type=overlay
        Options=lowerdir=/usr/lib/firmware,upperdir=/var/lib/state/firmware,workdir=/var/lib/state/firmware_work
        [Install]
        WantedBy=multi-user.target
```

---

## 4. Post-Reboot Verification & Health Checks

Once you reboot the node, run the following verification checks:

### 1. Verify Host-Side Modules & Devices
Confirm that the overlays are active and the driver is loaded:
```bash
# Check loaded modules
lsmod | grep amdgpu

# Confirm device paths are created
ls -la /dev/kfd /dev/dri
```

### 2. Verify Kubernetes Allocatable GPU Resources
Confirm that Kubernetes successfully discovers your 64GB GPU and lists it as allocatable:
```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:.status.capacity.amd\.com/gpu
```
*(Should return `1` for karnataka).*

### 3. Verify Pod Execution & Inference
* Check that the `vllm-rocm` pod transitions from `Pending` to `Running` and successfully loads the model:
  ```bash
  kubectl get pods -n vllm
  kubectl logs deployment/vllm-rocm -n vllm -f
  ```
* Submit a test chat completion API request over Tailscale:
  ```bash
  curl http://vllm.manatee-basking.ts.net/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
      "model": "Qwen/Qwen3.6-27B-FP8",
      "messages": [{"role": "user", "content": "Explain unified memory on AMD Strix Halo"}]
    }'
  ```
