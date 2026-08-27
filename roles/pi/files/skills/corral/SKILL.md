---
name: corral
description: Manage VMs across QEMU (local) and KubeVirt (Kubernetes) backends via the corral CLI. Create, start, stop, snapshot, SSH, and delete VMs. Supports bootc container VMs (direct from OCI images) and ISO-based installers. Use when the user wants to create/manage VMs, test bootable containers, or mentions corral, KubeVirt, libvirt, or VM testing.
---

# Corral VM Manager

Corral manages VMs across QEMU (local) and KubeVirt (Kubernetes) backends.
The KubeVirt backend runs on the cluster defined in `~/.kube/config`.

## Quick start — bootc VM

Create a bootc container VM (fastest path — installs from OCI image):

```bash
# List available bootc catalog images
corral bootc images

# Create a Bluefin VM (50Gi disk, 2 CPU, 4G RAM, default SSH key)
corral bootc create my-bluefin --image bluefin

# Use a different image: LTS, DX variant, or custom OCI ref
corral bootc create my-lts --image projectbluefin-bluefin-lts

# Wait for build + boot, then SSH
corral ssh my-bluefin

# Override size / node placement
corral bootc create big-vm --image centos-bootc-stream10 --cpu 4 --mem 8G --disk 100Gi --node karnataka

# Rebuild a VM from its latest image (upgrade)
corral bootc upgrade my-bluefin
```

## Quick start — ISO VM

For installer ISOs (Bluefin, Aurora, Fedora Workstation):

```bash
# List ISO images in the catalog
corral images

# Create from an ISO (use KubeVirt for server-mode; ISO installers need VNC)
corral create my-bluefin-vm --image bluefin-iso --disk 80G

# After install, corral autodetects SSH on the installed OS
corral ssh my-bluefin-vm
```

## VM lifecycle

```bash
# List all VMs
corral list

# Show VM details (IP, status, ports)
corral info my-vm

# Start/stop/restart
corral start  my-vm
corral stop   my-vm
corral restart my-vm

# Delete (irreversible — wipes disk)
corral delete my-vm

# Snapshot (KubeVirt only — saves PVC state)
corral snapshot create my-vm snap1
corral snapshot list   my-vm
corral snapshot revert my-vm snap1
```

## SSH and ports

```bash
# SSH with auto-discovered credentials
corral ssh my-vm

# SSH as a specific user
corral ssh my-vm --user fedora

# List exposed ports
corral info my-vm

# Bootc VMs auto-expose SSH. ISO VMs may need manual port mapping.
```

## Bootc plugin subcommands

```bash
corral bootc images                  # list catalog
corral bootc create <name> --image X # create from bootc image
corral bootc rebuild <name>          # rebuild disk from same image
corral bootc upgrade <name>          # rebuild from latest version
corral bootc switch <name> --image Y # switch to different image
corral bootc status                  # list bootc VMs + their images
```

## Diagnostics

```bash
corral logs my-vm       # tail VM console logs (KubeVirt)
corral doctor           # diagnose cluster setup issues
corral viewer my-vm     # launch VNC viewer (KubeVirt)
```

## Bluefin-specific notes

| Catalog name | Image | Use case |
|---|---|---|
| `bluefin` | `ghcr.io/ublue-os/bluefin:stable` | Latest Bluefin (bootc) |
| `projectbluefin-bluefin` | `ghcr.io/projectbluefin/bluefin:stable` | Project Bluefin |
| `projectbluefin-bluefin-lts` | `ghcr.io/projectbluefin/bluefin-lts:latest` | CentOS-based LTS |
| `projectbluefin-dakota` | `ghcr.io/projectbluefin/dakota:latest` | Next-gen composefs |
| `bluefin-iso` | ISO installer | Traditional OSTree install |

Use `corral bootc` for bootc-native images (fast, direct). Use `bluefin-iso`
when you need the traditional OSTree-based install path for migration testing.
