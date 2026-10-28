# Home Kubernetes Server Images

These are proposed bootable K3s images, not the current OS or workloads of either machine. Karnataka runs `ghcr.io/projectbluefin/utah:testing` with `multi-user.target` and a single-node K3s `v1.36.5+k3s1` server bound to tailnet address `100.66.158.127`; KubeVirt `v1.9.1`, CDI and Corral are installed. The `corral-vms/punjab` VM is staging, not a migrated replacement for active EC2 Punjab. Bihar's current OS and services are unverified. Verify image provenance and physical recovery before any future installation or switch.

The Utah-based images built in CI; the starter ISO was about 5.94 GiB.
Acceptance allows media up to 8 GiB, but the publication workflow still
rejects release assets of 2 GiB or more ([issue #351](https://github.com/hanthor/dotfiles/issues/351)).
In [CI](https://github.com/hanthor/dotfiles/actions/runs/40605226540), the
starter installer completed, but its installed VM never presented a serial
login within ten minutes; installation and cluster acceptance did not pass.
Utah's installed image retained a masked serial getty even though live media
unmasked it. A subsequent [CI run](https://github.com/hanthor/dotfiles/actions/runs/40622083319)
blocked the live serial getty while probing `/proc/tty/driver/serial`. The
image now guards the authenticated serial getty using the kernel's sysfs UART
type. A subsequent [CI run](https://github.com/hanthor/dotfiles/actions/runs/40623765935)
passed installer acceptance, including authenticated serial login, bootc switch
and a two-node K3s check. Physical serial recovery remains unverified.

## Image Variants

| Variant | Role | CPU/GPU | Image URI | Installer ISO |
|---------|------|---------|-----------|----------------|
| **bihar** | Proposed K3s control plane | Intel | `ghcr.io/hanthor/home-k8s-bihar:testing` | [Release](https://github.com/hanthor/dotfiles/releases) |
| **karnataka** | Proposed K3s worker | AMD Strix Halo | `ghcr.io/hanthor/home-k8s-karnataka:testing` | [Release](https://github.com/hanthor/dotfiles/releases) |
| **starter** | Disposable test/staging node | Any | `ghcr.io/hanthor/home-k8s-starter:testing` | [Release](https://github.com/hanthor/dotfiles/releases) |

## Image Composition

The intended images include the following; existing published tags may contain older builds, so inspect their provenance first:

- **Base:** `projectbluefin/utah` (Hummingbird + GNOME 51 desktop + Bluefin theming)
- **K3s:** Kubernetes v1.36.1 + SELinux policy
- **Storage:** iSCSI and NFS utilities
- **Networking:** NetworkManager, Tailscale, iptables-nft
- **GPU:** AMD firmware + amdgpu kernel driver included by the image build
- **Filesystems:** ext4, xfs, btrfs (all tools included)
- **Default state:** Multi-user target (text console), GDM masked
- **Serial recovery:** `serial-getty@ttyS0` uses normal authentication and
  starts only when the kernel reports a detected UART. Root autologin is
  restricted to the live installer, not the installed system. Physical serial
  recovery remains unverified.

## Obtaining Images

### Released artifacts

Download dated ISO releases from [GitHub Releases](https://github.com/hanthor/dotfiles/releases):
- `{bihar,karnataka,starter}-installer.iso` — offline bootc-installer-tui ISOs
- `{bihar,karnataka,starter}.oci.tar` — OCI archives for `bootc switch`
- `SHA256SUMS` — checksums for all artifacts
- `provenance.json` — builder details (source commits, acceptance proofs)

### Development/Testing

Build locally:
```bash
just server-images          # Builds all three variants to localhost/home-k8s-*:testing
just server-installer bihar ghcr.io/hanthor/home-k8s-bihar:testing artifacts/bihar.iso
```

### Container Registry

- **Tracking tags (mutable):** `ghcr.io/hanthor/home-k8s-{bihar,karnataka,starter}:testing`
- **Immutable tags (dated):** `ghcr.io/hanthor/home-k8s-{bihar,karnataka,starter}:YYYYMMDD`

Both are public (no login required).

## Proposed Installation (Not for Current Hosts)

The following is retained for planning and disposable testing, not a rollout instruction. Do not install, switch, reboot, or activate these profiles on Karnataka or other existing hosts: installation can wipe disks, and the proposed Karnataka agent conflicts with its current K3s server. Any future change requires a separately approved plan and independently verified backups. Preserve the historical Talos and AWS recovery material.

### From Installer ISO

1. **Boot the ISO** from USB stick (UEFI, Secure Boot must be disabled)
2. **At root console:**
   ```bash
   bootc-installer-tui
   ```
3. **Select image:** Custom URL → `oci:/usr/share/home-k8s/payload`
4. **Choose filesystem:** ext4 (default), xfs, or btrfs
5. **Set hostname:** `bihar`, `karnataka`, or `starter` (selects the proposed K3s role)
6. **Create admin user:** `nodeadmin` (or any name)
7. **Confirm and install**

The intended installed configuration includes:
- Disk partitioning (EFI + /boot + root)
- The proposed hostname-based K3s role (gated until explicit activation)
- Tailscale daemon (unenrolled at install time)
- SELinux enforcing mode

Verify these against the specific installer and artifact; the proposed image's
SELinux policy is not the current Utah/K3s configuration.

After reboot, the node boots to **text console** (multi-user.target). K3s is gated (disabled) until you manually enable it.

### From OCI Archive (bootc switch)

To upgrade an existing machine from a previous image:

```bash
# Download the OCI archive
wget https://github.com/hanthor/dotfiles/releases/download/home-k8s-20261021/home-k8s-bihar.oci.tar

# Extract locally
podman load -i home-k8s-bihar.oci.tar
# → Loads as ghcr.io/hanthor/home-k8s-bihar:testing

# Switch to new image
sudo bootc switch ghcr.io/hanthor/home-k8s-bihar:testing

# Reboot to apply
sudo systemctl reboot
```

## Filesystem Options

All three mkfs tools are included. Choose at install time or format a custom layout:

| Filesystem | Use case | Performance | Notes |
|-----------|----------|-------------|-------|
| **ext4** | Default, safe | Stable, widely supported | Verity-enabled for composefs |
| **xfs** | High-throughput, servers | Fast journal | Requires `mkfs.xfs` (included) |
| **btrfs** | Snapshots, COW | Modern, complex | Requires `mkfs.btrfs` + `btrfs` CLI |

The intended images include all three tools; verify the actual artifact. If a filesystem option fails to appear in the TUI, verify the mkfs tool exists: `which mkfs.xfs` etc.

## Graphical Target (Desktop)

Utah ships with GNOME desktop, but the images disable it by default (multi-user.target) for server use.

### Enable Graphical Target

```bash
# Simple toggle script (on the machine)
sudo toggle-graphical --reboot

# Or manually
sudo systemctl set-default graphical.target
sudo systemctl reboot
```

**What happens:**
- GDM (GNOME Display Manager) starts
- Full GNOME 51 desktop available
- Tailscale MagicDNS in system tray
- K3s still running (if enabled)

### Disable Graphical Target

```bash
sudo toggle-graphical --reboot
```

## K3s Enablement

In the proposed images, K3s is **installed but gated (disabled)** at boot. These hostname roles do not describe the current Karnataka server:

| Hostname | K3s Role | Service | Enabled at boot |
|----------|----------|---------|-----------------|
| `bihar` | server (control plane) | `k3s@server.service` | No (gated) |
| `karnataka` | agent (worker) | `k3s@agent.service` | No (gated) |
| `starter` | (none) | — | — |

To enable K3s on bihar (control plane):

```bash
sudo systemctl enable k3s@server.service
sudo systemctl start k3s@server.service

# Wait for API server
sudo systemctl status k3s@server.service
```

To enable K3s on karnataka (worker):

```bash
sudo systemctl enable k3s@agent.service
sudo systemctl start k3s@agent.service
```

Check that nodes joined the cluster:

```bash
kubectl get nodes -o wide
```

## Networking & Access

- **SSH:** `nodeadmin@{hostname}.manatee-basking.ts.net` (via Tailscale)
- **Kubeconfig:** At `/etc/rancher/k3s/k3s.yaml` (after K3s start)
- **Tailscale:** Daemon running, identity unenrolled (register via web UI or `sudo tailscale up`)

## Storage & Persistence

### iSCSI (Longhorn)

The proposed images intend to support Longhorn iSCSI workloads. Verify actual service, package and storage configuration on any target; do not assume a second Karnataka NVMe is usable (historically the WD Black was failing).

### Temporary Disks

```bash
# View all mounts
findmnt /

# Root filesystem type
lsblk -f /dev/sda3    # or appropriate root partition
```

## Image History & Migration

### Changes in Latest Release

**home-k8s-20261024:**
- Base switched from `os-minimal` to `utah` (added GNOME desktop)
- Filesystem detection in TUI (only shows available mkfs tools)
- `toggle-graphical` script for easy desktop on/off
- xfsprogs + btrfs-progs included (all filesystem tools)

**Previous release (home-k8s-20261021):**
- Hummingbird base (minimal, no desktop)
- ext4 only (xfs/btrfs not available)
- No toggle script

### Upgrading from Old Images

If you're running `home-k8s-20261021` or earlier, you can upgrade:

```bash
# Get the new OCI archive
wget https://github.com/hanthor/dotfiles/releases/download/home-k8s-20261024/home-k8s-bihar.oci.tar

podman load -i home-k8s-bihar.oci.tar
sudo bootc switch ghcr.io/hanthor/home-k8s-bihar:testing
sudo systemctl reboot
```

**Note:** Old images do not have `toggle-graphical`. Update to get the script.

## Troubleshooting

### TUI Filesystem Option Missing

If xfs or btrfs don't appear in the installer TUI filesystem picker:

```bash
# On the live ISO (at root console)
which mkfs.xfs    # Check if tool exists
which mkfs.btrfs
```

If missing, the image was built without those packages. Rebuild or wait for next release.

### K3s Won't Start

```bash
# Check service status
sudo systemctl status k3s@server.service
sudo journalctl -u k3s@server.service -n 50

# Verify kubeconfig exists
sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml get nodes
```

### Can't SSH After Graphical Enable

If you SSH while the system is switching targets, the SSH session may hang:

```bash
# On local machine, from another terminal
ssh nodeadmin@karnataka.manatee-basking.ts.net "sudo systemctl is-active graphical.target"

# Or just reboot the graphical machine and reconnect
```

### Tailscale Not Enrolled

Machines boot with Tailscale daemon running but unenrolled:

```bash
sudo tailscale up
# or web UI at: https://login.tailscale.com/admin/machines
```

## See Also

- [Talos K8s Cluster Handbook](./talos-k8s/cluster.md) — historical hardware, networking and recovery reference
- [AWS K8s Cluster Handbook](./aws-k8s/cluster.md) — historical cluster and recovery material
- [Roles Documentation](../roles/) — Individual role configurations
- [GitHub Releases](https://github.com/hanthor/dotfiles/releases) — Download ISOs and archives
