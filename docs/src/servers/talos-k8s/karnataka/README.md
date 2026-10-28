# Karnataka

Karnataka runs `ghcr.io/projectbluefin/utah:testing`, is in the fleet's
`server` inventory group, and uses `multi-user.target` as its default. SSH is
available over Tailscale at `100.66.158.127`. A single-node K3s cluster runs
KubeVirt, CDI, and Corral. The `corral-vms/punjab` VM is a staging guest; it
is not the EC2 host and has not received its data or services.

NetworkManager, Tailscale and SSH are enabled at boot. Ethernet is preferred;
a locally stored Wi-Fi profile autoconnects with a higher route metric. Wi-Fi
internet and SSH over Tailscale were verified with Ethernet connected; cable
failure and reboot failover have not been tested. The Tailscale device key
expires 2027-04-22 and may require reauthentication. Keep a console recovery
path before testing loss of the wired link.

Host DNS uses the systemd-resolved stub. Public DNS and MagicDNS resolved after
repair, but Tailscale later reported that its forwarder lacked upstream DNS;
inspect `tailscale status` if lookups fail. K3s uses a separate pod resolver.

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

Firewalld assigns `cni0` to `internal`, permitting forwarding within that
zone. A rich rule permits `10.42.0.0/16` to reach the Tailscale address on TCP
10250 for kubelet metrics. The `internal` zone's default services, including
SSH, are also reachable from pods; do not attach an untrusted interface to that
zone. The LAN interfaces are in `public`. Both bridge rules were present in
the permanent configuration when last inspected.

A runtime-only experiment enabling the existing `gateway-lan-to-world` policy
made pod HTTPS work. That policy accepts all traffic from `internal`, `home`
and `trusted` to both `public` and `external`, so it was disabled again and
must not be enabled as the fix. `home-k3s/firewall.sh` instead defines a
`k3s-pod-egress` policy: `internal` ingress, `public` egress, `CONTINUE`
target, and one IPv4 accept rule for source `10.42.0.0/16`. K3s supplies pod
masquerading; the policy does not alter NAT or host INPUT rules. It accepts all
protocols and ports from that CIDR, not just HTTPS: `public` includes the LAN
as well as Internet routes, so pods can reach LAN addresses. Source addresses
can be spoofed; this is not per-pod isolation. IPv6, other pod CIDRs and
non-`public` egress zones are not covered. Other firewalld/K3s rules may also
allow traffic; this policy is not a comprehensive egress firewall.

The new policy has **not been applied or verified on Karnataka**. The host
has no console recovery, and a rollback timer has not been proven there. Do
not treat the checked-in policy as a persistent fix until the guarded rollout
below succeeds. `sudo bash home-k3s/firewall.sh --check` inspects both stores
without changes. `--apply` refuses foreign interface/source bindings and policy
drift instead of taking over a broader policy. Firewalld 2.5.2 can create a
policy only in the permanent store, so the first `--apply` stages it there but
returns nonzero while the policy is absent at runtime. It never reloads
firewalld. Interrupted creation may leave a partial policy; a later apply can
finish it. Other policies are not changed.

### Guarded rollout and rollback

First establish console recovery, retain an existing Tailscale SSH session,
and make sure a second independent SSH session can connect. Do not reload or
restart firewalld. From a trusted checkout on Karnataka, prove that a root
systemd transient timer actually fires before relying on one (the probe only
creates a marker in `/run`):

```bash
sudo test ! -e /run/k3s-fw-probe
sudo systemd-run --unit=k3s-fw-probe --on-active=5s /usr/bin/touch /run/k3s-fw-probe
sleep 10
sudo test -f /run/k3s-fw-probe
sudo rm /run/k3s-fw-probe
```

Inspect `sudo firewall-cmd --list-all-zones` and `sudo firewall-cmd
--list-all-policies`, then repeat both with `--permanent`. Source bindings
take precedence over interface bindings; investigate any source overlapping
the pod CIDR or any other forwarding policy that could change the expected
scope. The script checks the `internal` bindings and its own policy, not all
other policies. Stop if the resulting exposure is not understood.

Stop if the marker does not appear. Before scheduling rollback, require the
policy to be absent in **both** stores and the existing bridge setup already
complete, so the rollback below reverts every change this apply can make:

```bash
sudo bash -s <<'CHECK'
set -euo pipefail
rule='rule family="ipv4" source address="10.42.0.0/16" destination address="100.66.158.127/32" port port="10250" protocol="tcp" accept'
firewall-cmd --state >/dev/null
[[ $(firewall-cmd --get-default-zone) != internal ]]
for scope in runtime permanent; do
  opts=(); [[ $scope == runtime ]] || opts=(--permanent)
  [[ $(firewall-cmd "${opts[@]}" --zone=internal --list-interfaces) == cni0 ]]
  [[ -z $(firewall-cmd "${opts[@]}" --zone=internal --list-sources) ]]
  [[ " $(firewall-cmd "${opts[@]}" --get-policies) " != *' k3s-pod-egress '* ]]
  firewall-cmd --quiet "${opts[@]}" --zone=internal --query-interface=cni0
  firewall-cmd --quiet "${opts[@]}" --zone=internal --query-forward
  firewall-cmd --quiet "${opts[@]}" --zone=internal --query-rich-rule="$rule"
done
CHECK
```

If any prerequisite fails, stop and investigate; this rollback is only for a
new permanent policy, not for changes to the bridge zone. Schedule the
rollback and confirm the timer is active **before** staging. It deletes only
the new permanent policy and does not reload firewalld:

```bash
sudo systemd-run --unit=k3s-egress-rollback --on-active=15m \
  /usr/bin/firewall-cmd --permanent --delete-policy=k3s-pod-egress
sudo systemctl is-active --quiet k3s-egress-rollback.timer
sudo systemctl list-timers k3s-egress-rollback.timer
```

Stop if the timer is not active. Then run `sudo bash home-k3s/firewall.sh
--apply`. On first staging, a nonzero result and `Permanent k3s-pod-egress
staged; runtime policy is absent` are expected; any other error means stop and
leave the timer armed. Inspect the staged policy and permanent configuration:

```bash
sudo firewall-cmd --permanent --info-policy=k3s-pod-egress
sudo firewall-cmd --check-config
sudo bash home-k3s/firewall.sh --check
```

The policy must show target `CONTINUE`, priority `-1`, only `internal` ingress,
only `public` egress, and only the documented IPv4 rich rule; the last command
must report `Missing policy k3s-pod-egress (runtime)` and exit nonzero. If
anything else fails, leave the timer armed. Otherwise cancel the timer well
before it expires with `sudo systemctl stop k3s-egress-rollback.timer` and
confirm it is inactive. If it fires, inspect `journalctl -u
k3s-egress-rollback.service` and confirm the policy is absent with `sudo
firewall-cmd --permanent --get-policies`. If rollback fails, use the console
to run `sudo firewall-cmd --permanent --delete-policy=k3s-pod-egress`.

The staged policy will only become active when firewalld next starts from its
permanent configuration. Do not reload or restart it live. Arrange a controlled
reboot only with console recovery available, then confirm a **new** Tailscale
SSH connection, run `sudo bash home-k3s/firewall.sh --check`, and test pod DNS
plus HTTPS, for example with a disposable pod:

```bash
sudo /var/usrlocal/bin/k3s kubectl --server https://100.66.158.127:6443 \
  run firewall-egress-probe --rm -i --restart=Never --image=curlimages/curl:8.10.1 \
  --command -- curl -4 -fsS --max-time 15 -o /dev/null https://example.com/
```

If the post-boot checks fail, use the console, delete the permanent policy with
`sudo firewall-cmd --permanent --delete-policy=k3s-pod-egress`, and reboot
under console supervision to remove it from runtime. Removing a permanent
policy does not change runtime. Do not use `--runtime-to-permanent`, which
would overwrite unrelated permanent configuration.

K3s logged `iptables-save` nftables parsing errors during network-policy
reconciliation. No NetworkPolicy objects were present when checked. Policy
enforcement has not been verified; do not rely on it for isolation until the
iptables/nftables incompatibility is resolved and enforcement is tested.

## Historical configuration

Karnataka was the worker of the home Talos cluster. The [cluster handbook](../cluster.md),
Talos manifests and configs, and Bitwarden notes are retained as historical
recovery material; they do not establish its current OS or workloads.
