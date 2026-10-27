# Karnataka

Karnataka runs `ghcr.io/projectbluefin/utah:testing`, is in the fleet's
`server` inventory group, and uses `multi-user.target` as its default. SSH is
available over Tailscale at `100.66.158.127`. A single-node K3s cluster runs
KubeVirt, CDI, and Corral. The `corral-vms/punjab` VM is a staging guest; it
is not the EC2 host and has not received its data or services.

As last checked, the fleet update timer is not installed and user linger is
disabled. The native-unit changes are under review; do not enable unattended
updates from the unmerged checkout.

## Hardware

- Arch: x86_64
- System: [Framework Computer](https://frame.work/)
- CPU: [AMD Strix Halo APU](https://www.amd.com/en/products/processors/laptop/ryzen-ai-max-plus.html)
- GPU: AMD integrated
- LAN: DHCP on the home network

## K3s operation

The host-specific files are in `home-k3s/`. K3s listens on the Tailscale
address, and its service waits for that address before starting. The service
loads `br_netfilter` and `overlay` when available. Run `systemctl status k3s`
and `sudo /var/usrlocal/bin/k3s kubectl --server https://100.66.158.127:6443 get pods -A`
to inspect it. Reloading the service definition does not restart K3s.

`home-k3s/install-host.sh` reuses the pinned binary and refuses to replace a
different binary while K3s is active. It does not restart an active service;
changes to server configuration take effect on the next start. The separate
`home-k3s/apply-stack.sh` uses conflict-checked server-side apply and is not
transactional: review ownership conflicts before retrying. The storage profile
and Corral manifests passed server-side dry-run against the current cluster;
operator and resource reapplication has not been exercised on it.

Corral has no authentication in this deployment. Its ClusterIP is reachable
from cluster workloads and its service account can manage cluster resources;
only run trusted workloads, and do not expose the dashboard publicly.

Host SELinux is enforcing and `container-selinux` is installed. The running
Utah image does not include `k3s-selinux`, and its policy store is read-only;
K3s SELinux container labeling remains disabled. Our proposed image build
includes the policy, but has not been installed on this host. Do not enable
K3s SELinux until the policy and workload labeling are verified. The default
local-path volumes are node-local, without snapshot or expansion support;
deleting a claim deletes its data.

Firewalld assigns `cni0` to the `internal` zone, permitting forwarding within
that zone. A rich rule permits `10.42.0.0/16` to reach the Tailscale address on
TCP port 10250 for kubelet metrics. The `internal` zone's default services,
including SSH, are also reachable from pods; do not attach an untrusted
interface to that zone. The public LAN interface remains in `public`. Both
bridge rules are present in the permanent configuration. On Karnataka,
`sudo bash home-k3s/firewall.sh --check` inspects both runtime and permanent
state without changes. `--apply` is an explicit repair operation; it does not
reload firewalld and refuses unrelated interfaces or source bindings in the
`internal` zone. Keep a recovery path available for any firewall change.

K3s logged `iptables-save` nftables parsing errors during network-policy
reconciliation. No NetworkPolicy objects were present when checked. Policy
enforcement has not been verified; do not rely on it for isolation until the
iptables/nftables incompatibility is resolved and enforcement is tested.

## Historical configuration

Karnataka was the worker of the home Talos cluster. The [cluster handbook](../cluster.md),
Talos manifests and configs, and Bitwarden notes are retained as historical
recovery material; they do not establish its current OS or workloads.
