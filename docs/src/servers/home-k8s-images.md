# Home Kubernetes Server Images

Bootable container images for the home K8s cluster (bihar, karnataka, starter). Built from **Fedora Hummingbird + GNOME desktop + K3s**, with graphical target disabled by default.

## Image Variants

| Variant | Role | CPU/GPU | Image URI | Installer ISO |
|---------|------|---------|-----------|----------------|
| **bihar** | K3s control plane | Intel | `ghcr.io/hanthor/home-k8s-bihar:latest` | [Release](https://github.com/hanthor/dotfiles/releases) |
| **karnataka** | K3s worker (AMD APU + GPU) | AMD Strix Halo | `ghcr.io/hanthor/home-k8s-karnataka:latest` | [Release](https://github.com/hanthor/dotfiles/releases) |
| **starter** | Disposable test/staging node | Any | `ghcr.io/hanthor/home-k8s-starter:latest` | [Release](https://github.com/hanthor/dotfiles/releases) |

## Image Composition

Each image includes:

- **Base:** `projectbluefin/utah:stable`, pinned by digest (Hummingbird + GNOME 51 desktop + Bluefin theming). Utah is experimental pre-alpha, including its stable stream.
- **K3s:** Kubernetes v1.36.1 + SELinux policy
- **Storage:** iSCSI utils, NFS utils, Longhorn tools
- **Networking:** NetworkManager, Tailscale, iptables-nft
- **GPU:** AMD firmware + amdgpu kernel driver (built into boot image via Talos Image Factory)
- **Filesystems:** ext4, xfs, btrfs (all tools included)
- **Default state:** Multi-user target (text console), GDM masked

## Obtaining Images

### Latest Release (Recommended)

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

## Installation

### From Installer ISO

1. **Boot the ISO** from USB stick (UEFI, Secure Boot must be disabled)
2. **At root console:**
   ```bash
   bootc-installer-tui
   ```
3. **Select image:** Custom URL → `oci:/usr/share/home-k8s/payload`
4. **Choose filesystem:** ext4 (default), xfs, or btrfs
5. **Set hostname:** `bihar`, `karnataka`, or `starter` (enables K3s role)
6. **Create admin user:** `nodeadmin` (or any name)
7. **Confirm and install**

The TUI automatically configures:
- Disk partitioning (EFI + /boot + root)
- K3s service enablement (based on hostname)
- Tailscale daemon (unenrolled at install time)
- SELinux enforcing mode

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

Deployed images support all three without additional tools. If a filesystem option fails to appear in the TUI, verify the mkfs tool exists: `which mkfs.xfs` etc.

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

K3s is **installed but gated (disabled)** at boot. Roles are determined by hostname:

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

Both nodes are configured for Longhorn iSCSI workloads:
- `iscsid.socket` running
- `iscsi-initiator-utils` installed
- Unique initiator name generated at first boot
- `/var/lib/longhorn/` mounted to second NVMe (karnataka only)

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

- [Talos K8s Cluster Handbook](./talos-k8s/cluster.md) — Bihar & karnataka hardware, networking, advanced operations
- [AWS K8s Cluster Handbook](./aws-k8s/cluster.md) — Production cluster migration info
- [Roles Documentation](../roles/) — Individual role configurations
- [GitHub Releases](https://github.com/hanthor/dotfiles/releases) — Download ISOs and archives
