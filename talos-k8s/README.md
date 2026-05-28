# Talos Linux 2-Node Kubernetes Cluster with AMD GPU Acceleration

This directory contains the complete infrastructure-as-code configurations, manifests, and documentation for a highly custom, high-performance 2-node Kubernetes cluster utilizing **Talos Linux (v1.13.2)**, designed specifically for running hardware-accelerated LLM workloads (via **vLLM**) and virtualized infrastructure (via **KubeVirt**).

---

## 1. Cluster Architecture

The cluster consists of two physical nodes connected on the local network (LAN) with customized hostnames and static IPs:

| Hostname | Role | IP Address | Hardware Context | Target Boot Disk |
| :--- | :--- | :--- | :--- | :--- |
| **`Bihar`** | Control Plane | `192.168.0.5` | Standard CPU node | `/dev/nvme0n1` |
| **`Karnataka`** | Worker | `192.168.0.6` | AMD Ryzen AI Max 300 Series (Strix Halo APU) | `/dev/nvme0n1` |

* **Kubernetes Version:** `v1.36.1`
* **Talos Version:** `v1.13.2` (Downgraded from `v1.13.3` to avoid upstream AMD64 registry multi-arch manifest pull errors).

---

## 2. Talos Linux AMD GPU Customization

Because Talos Linux runs an immutable, read-only root filesystem, standard GPU driver compilation or runtime injection is not possible. To expose the integrated AMD Strix Halo GPU (RDNA 3.5 architecture), we baked the official AMD GPU kernel modules directly into the Talos boot image.

### Custom Image Schematic ID
Using the Talos Image Factory, we generated the following schematic containing the GPU kernel extensions:
* **Schematic ID:** `b6ab12edc37d4a92a0705f4f2f12952d5a1a3f38b51783422b56810b60e230fd`
* **Baked Extensions:**
  * `siderolabs/amdgpu` (AMD GPU kernel driver)
  * `siderolabs/amd-ucode` (AMD microcode firmware)

The installer image is configured in [worker.yaml](worker.yaml) under `machine.install.image` as:
`factory.talos.dev/installer/b6ab12edc37d4a92a0705f4f2f12952d5a1a3f38b51783422b56810b60e230fd:v1.13.2`

Upon upgrade, this forces the node to load the GPU driver automatically, making `/dev/dri/card0`, `/dev/dri/renderD128`, and `/dev/kfd` available on the host!

---

## 3. NVMe Boot Disk Overrides

Default Talos installation configs target `/dev/sda` (which is often the live USB installer). If applied unmodified, it will overwrite the boot medium and crash. We patched both node configurations (`controlplane.yaml` and `worker.yaml`) to install onto high-speed NVMe SSD drives:
```yaml
machine:
  install:
    disk: /dev/nvme0n1
```

---

## 4. AMD GPU Kubernetes Integration

To expose and schedule the GPU resources inside Kubernetes, we deployed the official AMD GPU device plugin and node labeller.

### Exposing `amd.com/gpu`
The device plugin detects `/dev/kfd` and `/dev/dri/renderD128` and registers them as scheduling capacities.
1. **Device Plugin DaemonSet:**
   ```bash
   kubectl apply -f https://raw.githubusercontent.com/ROCm/k8s-device-plugin/master/k8s-ds-amdgpu-dp.yaml
   ```
2. **Node Labeller DaemonSet:**
   ```bash
   kubectl apply -f https://raw.githubusercontent.com/ROCm/k8s-device-plugin/master/k8s-ds-amdgpu-labeller.yaml
   ```

Once deployed, the labeller automatically detects the APU and assigns hardware capabilities as labels (e.g., `amd.com/gpu.product-name=AMD_Radeon_8060S_Graphics` and `amd.com/gpu.vram=64G`). The GPU is exposed as an allocatable resource:
`amd.com/gpu: "1"`

---

## 5. Virtualization with KubeVirt & Web UI

We installed **KubeVirt v1.8.2** to run hypervisor-based VM workloads side-by-side with containers.

### Core Installation
The operator handles provisioning all virtualization APIs:
```bash
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.2/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.2/kubevirt-cr.yaml
```

### KubeVirt Manager Web UI
To manage virtual machines through a rich dashboard instead of manual YAML, we installed the community **KubeVirt Manager**:
```bash
kubectl apply -f https://raw.githubusercontent.com/kubevirt-manager/kubevirt-manager/main/kubernetes/bundled.yaml
```

#### Accessing the Dashboard
To access the KubeVirt Manager dashboard from your local computer, use port-forwarding:
```bash
kubectl port-forward svc/kubevirt-manager 8080:8080 -n kubevirt-manager
```
Once forwarded, open your browser and navigate to:
**`http://localhost:8080`**

---

## 6. Hardware-Accelerated vLLM (Strix Halo APU)

The worker node `Karnataka` houses the AMD Strix Halo APU with high-bandwidth unified VRAM. Because this integrated RDNA 3.5 architecture is non-standard, PyTorch and ROCm require specific environment overrides to bypass driver bugs and compile shaders correctly.

### vLLM Deployment Manifest ([vllm-deployment.yaml](vllm-deployment.yaml))
Key features implemented in the vLLM deployment:
* **Node Scheduling:** Strict `nodeSelector` targeted at `karnataka` to leverage its APU.
* **Namespace Security Bypass:** We labeled the `default` namespace as `privileged` so the container can request `hostPath` mounts, shared memory allocations, and `SYS_PTRACE` capabilities.
  ```bash
  kubectl label ns default pod-security.kubernetes.io/enforce=privileged --overwrite
  ```
* **ROCm & Strix Halo Environment Overrides:**
  * `HSA_OVERRIDE_GFX_VERSION: "11.5.1"` — Forces ROCm to treat the Strix Halo RDNA 3.5 APU (gfx1151) as supported hardware.
  * `PYTORCH_ROCM_ARCH: "gfx1151"` — Compiles/runs PyTorch operators matching the exact GPU architecture.
  * `HSA_XNACK: "1"` & `HSA_FORCE_FINE_GRAIN_PCIE: "1"` — Enables unified memory and fine-grained virtual memory access.
  * `VLLM_ROCM_USE_AITER: "0"` — Disables Aiter/Triton compilation pathways that cause GPU driver halts on RDNA 3.5.
* **vLLM Command Arguments:**
  * `--model Qwen/Qwen2.5-1.5B-Instruct` — Fast downloading, highly capable testing model.
  * `--enforce-eager` — Bypasses ROCm driver graph capture hangs by forcing PyTorch eager execution.
* **Resource and Memory Limits:**
  * Requests `amd.com/gpu: "1"` limit to map host render devices.
  * Maps an `emptyDir` memory volume to `/dev/shm` (size `16Gi`) for ROCm inter-process communications.
  * Maps host cache `/var/tmp/huggingface` to `/root/.cache/huggingface` to persist downloaded LLM models.

---

## 7. How to Redeploy or Interact

Use `talosctl` directly for secure node operations (bypassing any external SaaS tool like Omni):
```bash
# Verify cluster health
talosctl -e 192.168.0.5 -n 192.168.0.5 health

# Inspect worker node dmesg logs for graphics initialization
talosctl -e 192.168.0.6 -n 192.168.0.6 dmesg | grep -i amdgpu

# Check exposed GPU devices on worker
talosctl -e 192.168.0.6 -n 192.168.0.6 list /dev/dri/
```

Use `kubectl` to manage pods and services:
```bash
# Monitor deployment status
kubectl get pods -n kubevirt
kubectl get pods -n kubevirt-manager
kubectl get pods -w

# Check vLLM server API status
kubectl logs -f deployment/vllm-openai
```
