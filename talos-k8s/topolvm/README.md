# TopoLVM — Local NVMe storage with snapshots & expansion

TopoLVM provides **local NVMe-backed persistent storage** with LVM thin provisioning,
giving us the speed of `local-path` with the snapshot/expansion features of Longhorn.

## Why (not just Longhorn)

| Feature | Longhorn | local-path | TopoLVM |
|---|---|---|---|
| Speed | ⚠️ iSCSI network IO (slow) | ✅ Local NVMe | ✅ Local NVMe |
| Snapshots | ✅ | ❌ | ✅ (LVM thin) |
| Volume expansion | ✅ | ❌ | ✅ (LVE resize) |
| Replication | ✅ (3x) | ❌ | ❌ (single node) |
| Online migration | ❌ (mixed CPU vendors) | ❌ | ❌ |

Trade-off: no replication → single point of failure for storage. Acceptable for
a home-lab build VM — the data is easily reproducible.

## Cluster disk layout

| Node | Disk | Size | Purpose |
|---|---|---|---|
| **bihar** | `/dev/nvme0n1` (Sabrent 1TB) | 1 TB | Talos OS + local-path |
| **karnataka** | `/dev/nvme0n1` (Sabrent 1TB) | 1 TB | Talos OS + local-path |
| **karnataka** | `/dev/nvme1n1` (Crucial P3 Plus 1TB) | 1 TB | **TopoLVM thin pool** |

Two NVMes on karnataka makes it the ideal node for TopoLVM-backed VMs (like hyderabad).

## Deployment plan

### 1. Generate Talos system extension image with LVM

TopoLVM needs `lvm2` userspace tools and the `device-mapper` kernel module on the host.
Talos provides a `siderolabs/lvm` system extension. Generate a new installer image
via the [Image Factory](https://factory.talos.dev):

```bash
# Current schematic ID (GPU + UVM)
# b6ab12edc37d4a92a0705f4f2f12952d5a1a3f38b51783422b56810b60e230fd

# New schematic adding siderolabs/lvm extension:
# factory.talos.dev/installer/<new-schematic-id>:v1.13.4
```

The factory schematic should include:

```yaml
# schematic.yaml
customization:
  extraKernelArgs: []
  systemExtensions:
    officialExtensions:
      - siderolabs/lvm   # <-- ADD for LVM2 tools
      - siderolabs/amdgpu
      - siderolabs/amd-ucode
```

Install the new image with `talosctl upgrade`:
```bash
talosctl upgrade \
  --image factory.talos.dev/installer/<new-schematic-id>:v1.13.4 \
  -n 192.168.0.6      # karnataka only (only node with second NVMe)
```

### 2. Prepare the thin pool disk

After upgrade, partition `/dev/nvme1n1` on karnataka for LVM:

```bash
# Create a single partition covering the whole disk
talosctl -n 192.168.0.6 shell -- parted /dev/nvme1n1 mklabel gpt
talosctl -n 192.168.0.6 shell -- parted /dev/nvme1n1 mkpart primary 0% 100%
talosctl -n 192.168.0.6 shell -- parted /dev/nvme1n1 set 1 lvm on

# Create LVM thin pool
talosctl -n 192.168.0.6 shell -- pvcreate /dev/nvme1n1p1
talosctl -n 192.168.0.6 shell -- vgcreate vg1 /dev/nvme1n1p1
talosctl -n 192.168.0.6 shell -- lvcreate -L 800G -T vg1/thinpool
```

> **Note:** 800G out of ~930G usable — leaves headroom for metadata and snapshots.

### 3. Deploy TopoLVM via Helm

```bash
helm repo add topolvm https://topolvm.github.io/topolvm
helm install topolvm topolvm/topolvm \
  --namespace topolvm-system \
  --create-namespace \
  --values talos-k8s/topolvm/values.yaml
```

With values:

```yaml
# values.yaml
scheduler:
  create: true
lvmd:
  deviceClasses:
    - name: ssd
      volumeGroup: vg1
      thinPool: thinpool
      default: true
  managed: true
node:
  extraVolumeMounts:
    - name: device-mapper
      mountPath: /run/udev
  tolerations:
    - operator: Exists
```

### 4. Create StorageClass

```yaml
# storage-class.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: topolvm-ssd
provisioner: topolvm.io
parameters:
  device-class: ssd
  csi.storage.k8s.io/fstype: ext4
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
```

### 5. Create VolumeSnapshotClass

```yaml
# volumesnapshotclass.yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: topolvm-ssd
driver: topolvm.io
deletionPolicy: Delete
```

### 6. Test with a PVC

```yaml
# test-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: topolvm-test
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: topolvm-ssd
```

```bash
kubectl apply -f test-pvc.yaml
# Should bind instantly (no network - local NVMe)
```

## Migration strategy

### For hyderabad

```bash
# 1. Push current image to ghcr (preserve build state)
podman push localhost/albacore:gnome-live ghcr.io/tuna-os/albacore:gnome-live

# 2. Delete hyderabad & its Longhorn PVCs
corral delete hyderabad -f
kubectl delete pvc hyderabad-data -n corral-vms

# 3. Recreate with TopoLVM storage class
# (After corral gets --storage-class support, or manually annotate PVC)
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: hyderabad-data
  namespace: corral-vms
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 60Gi
  storageClassName: topolvm-ssd
EOF

# 4. Recreate VM pointing to the existing PVC
corral create hyderabad --kubevirt --pvc hyderabad-data \
  --container-disk quay.io/containerdisks/fedora:44 \
  --cpu 8 --mem 16G --node karnataka

# 5. Pull image and continue
corral ssh hyderabad -u fedora -- podman pull ghcr.io/tuna-os/albacore:gnome-live
corral start hyderabad
```

### For future VMs

Add a `--storage-class` flag to corral so new VMs can pick `topolvm-ssd` directly.

## Comparison: Longhorn vs TopoLVM on this cluster

| | Longhorn | TopoLVM |
|---|---|---|
| Provisioner | `driver.longhorn.io` | `topolvm.io` |
| Backend device | iSCSI (network) | LVM thin (local NVMe) |
| Latency | ~500μs–2ms | ~10–50μs |
| `podman save\|load` 7GB | ~40 min | ~30 sec |
| Snapshots | ✅ | ✅ (atomic LVM) |
| Expansion | ✅ | ✅ |
| Replication | 3x (multi-node) | none (single NVMe) |
| Disk used | `/dev/sdd` (Longhorn replica) | `/dev/nvme1n1p1` (Crucial P3 Plus) |

## Risks & mitigation

1. **Single node failure** — TopoLVM volumes are local to karnataka. If karnataka
   dies, all PVCs are inaccessible. Mitigation: home-lab, data is build artifacts
   (reproducible). Critical data lives on Longhorn (appflowy, forgejo, authentik).
2. **LVM thin pool fills** — Thin pool exhaustion can corrupt ALL volumes in the
   pool. Mitigation: monitor with Prometheus (`lvmd_thin_pool_usage_bytes`),
   alert at 80%. Leave spare capacity (800G of 930G).
3. **Talos upgrade** — The LVM extension is tied to kernel version. Upgrading
   Talos requires a matching LVM extension. Mitigation: use the Image Factory
   to regenerate the installer with both LVM + AMD GPU extensions together.
