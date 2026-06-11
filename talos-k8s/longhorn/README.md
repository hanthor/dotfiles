# Longhorn storage on Talos

Longhorn provides replicated block storage with **online expansion** and
**CSI volume snapshots** — which `local-path` cannot do. Corral uses it for new
VM disks (snapshots, clone, expand). It does **not** enable cross-vendor live
migration (KubeVirt pins migration targets to the source node's CPU vendor, and
bihar=Intel / karnataka=AMD — see `docs/.../cluster.md`).

Installed 2026-06-11, Longhorn **v1.12.0**.

## 1. Node prerequisites (Image Factory schematic + iscsi)

Longhorn needs `iscsid` and `nsenter`/`fstrim`, provided by Talos system
extensions baked into a new installer image.

**Schematic** (`schematic.yaml`) = the existing `amdgpu` plus `iscsi-tools` and
`util-linux-tools`:

```
amdgpu + iscsi-tools + util-linux-tools
→ schematic ID: 3a33ec6dfc8cfd61d2a3db3caf97894f31e913952d71ce3c3fbbe565a3f08339
→ image: factory.talos.dev/installer/3a33ec6dfc8cfd61d2a3db3caf97894f31e913952d71ce3c3fbbe565a3f08339:v1.13.2
```

Regenerate with: `curl -X POST --data-binary @schematic.yaml https://factory.talos.dev/schematics`

## 2. Machine config + upgrade (per node, REBOOTS)

`patch.yaml` sets `machine.install.image` to the new schematic and bind-mounts
`/var/lib/longhorn` into the kubelet (Longhorn's default data path).

```bash
# Apply to each node, then upgrade (reboots into the iscsi schematic):
talosctl -n <ip> patch machineconfig --patch @patch.yaml
talosctl -n <ip> upgrade --image factory.talos.dev/installer/<ID>:v1.13.2

# Do the worker (karnataka 192.168.0.6) first, verify, then the control plane
# (bihar 192.168.0.5). NOTE: the control plane drain fails on KubeVirt PDBs —
# upgrade it with --drain=false (Talos reboots gracefully regardless), then
# `kubectl uncordon bihar`.
```

Verify per node: `talosctl -n <ip> get extensions` shows `iscsi-tools` +
`util-linux-tools`; `talosctl -n <ip> services ext-iscsid` is Running.

## 3. Longhorn + snapshot stack

```bash
kubectl apply -f https://raw.githubusercontent.com/longhorn/longhorn/v1.12.0/deploy/longhorn.yaml
kubectl label ns longhorn-system pod-security.kubernetes.io/enforce=privileged --overwrite
# Longhorn marks itself default — keep local-path the cluster default instead:
kubectl patch sc longhorn -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"false"}}}'

# External-snapshotter (Longhorn does NOT bundle it) — CRDs + controller:
SNAP=v8.2.0
for c in volumesnapshotclasses volumesnapshotcontents volumesnapshots; do
  kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/$SNAP/client/config/crd/snapshot.storage.k8s.io_$c.yaml
done
kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/$SNAP/deploy/kubernetes/snapshot-controller/rbac-snapshot-controller.yaml
kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/$SNAP/deploy/kubernetes/snapshot-controller/setup-snapshot-controller.yaml

kubectl apply -f volumesnapshotclass.yaml   # Longhorn VolumeSnapshotClass
```

## Result

- StorageClass `longhorn` (`allowVolumeExpansion: true`); `local-path` stays the
  cluster default. Corral picks `longhorn` explicitly for new VM disks.
- `VolumeSnapshotClass longhorn-snapshot` → KubeVirt `VirtualMachineSnapshot`
  works for persistent VMs.
- Corral `/api/capabilities` → `{storageClass: longhorn, canExpand: true, canSnapshot: true}`.
