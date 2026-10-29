# KubeVirt on the AWS cluster (tailnet-only corral)

> **Historical AWS deployment only.** The AWS root module and node startup helper
> have been retired. Their source and original deployment instructions are
> archived at [`dcbbfbc`](https://github.com/hanthor/dotfiles/tree/dcbbfbc/talos-k8s/kubevirt-aws).
> Restoring them can recreate paid resources. These retained Kubernetes manifests
> are recovery reference, not the active Karnataka K3s/KubeVirt configuration.
> Final AWS deletion on **2026-10-29** removed AWS volumes, owned snapshots and
> all three S3 buckets, including backups and OpenTofu state. The disk-persistence
> caveat below describes historical stop/start behavior, not surviving storage.
> See the [final deletion evidence](../../docs/src/servers/aws/README.md).

A Proxmox-style VM host on the AWS Talos cluster: KubeVirt VMs on a
dedicated node, managed through corral-web at `https://corral-aws.<tailnet>.ts.net`.
There is no public ingress; the node has no public services, and corral-web is
published only through the Tailscale operator.

| Piece | Where |
|---|---|
| Node: m7i.2xlarge with nested virtualization, tainted for VMs only | Archived `aws/kubevirt.tf` at `dcbbfbc` |
| Spend kill switch: AWS Budgets stops the node at $1100 gross/month | Archived `aws/kubevirt.tf` at `dcbbfbc` |
| Idle stop after 30 minutes with no VM pods | `idle-stop.yaml` |
| Start on demand | Archived `scripts/kubevirt-node` at `dcbbfbc` |
| KubeVirt/CDI placement (infra on always-on nodes, VMs on the node) | `kubevirt-cr.yaml` |
| corral-web as `corral-aws` on the tailnet | `kustomization.yaml` |

**Cost:** $0.4284/h while running (~$313/month if it never stopped) plus
150 GB gp3 (~$13/month). Stopped, it costs only the disk. At the time of
writing (2026-09-24) gross spend forecast was ~$364/month against $1400/month
credits.

## Bring-up (once)

The original bring-up and daily power-management commands are preserved in the
[runbook at `dcbbfbc`](https://github.com/hanthor/dotfiles/blob/dcbbfbc/talos-k8s/kubevirt-aws/README.md).
They depend on the retired AWS root module and startup helper and are not active
commands in this checkout. Do not apply these historical instructions to the
[current Karnataka K3s host](../../docs/src/servers/talos-k8s/karnataka/README.md).

## Caveats

- Nested virtualization costs some CPU performance. It's fine for test VMs
  and CI, but not for heavy builds.
- Stopping the node stops its VMs. Disks persist, because the root volume
  survives a stop, but anything in RAM is lost. `down` shuts VMs down first;
  idle-stop only fires when no VMs are running.
- The public IP changes on every start. Nothing depends on it after the join:
  the node reaches the control plane over the VPC.
