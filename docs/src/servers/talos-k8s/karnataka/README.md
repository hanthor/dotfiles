# Karnataka — Utah and the active K3s cluster

Karnataka runs `ghcr.io/projectbluefin/utah:testing`, is in the fleet's
`server` inventory group, and uses `multi-user.target` as its default. SSH is
available over Tailscale at `100.66.158.127`. A single-node K3s cluster runs
KubeVirt, CDI, and Corral. The `corral-vms/punjab` VM now runs the migrated
Punjab environment at `100.103.187.46` (tailnet name `punjab`). This is the
[active replacement](../../punjab/README.md), not a staging VM or an EC2 host.
For the former EC2 host's retirement and retained recovery artifacts, consult
the [AWS account handbook](../../aws/README.md).

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

## Current K3s cluster

Read-only inspection on **2026-10-29** found:

| Component | Live state |
|-----------|------------|
| API endpoint | `https://100.66.158.127:6443` over Tailscale |
| Client context | `karnataka-k3s` |
| Node | `karnataka`, `Ready`, control-plane, internal IP `100.66.158.127`, no external IP |
| Kubernetes | K3s `v1.36.5+k3s1`, containerd `2.3.4-k3s1.36` |
| Host image | Bluefin `testing-20261024-9acbde2`, kernel `7.2.11-200.fc44.x86_64` |
| Core services | CoreDNS, metrics-server and local-path-provisioner; deployments available |
| Virtualization | KubeVirt `v1.9.1` and CDI `v1.66.1`, both `Deployed` |
| Corral | `corral/corral-web`, available, ClusterIP service on port 80 |
| Storage | Default `local-path`, `rancher.io/local-path`, `WaitForFirstConsumer`, reclaim policy `Delete`, no expansion |
| Persistent claims | Bound `corral-vms/punjab-root` and `karnataka-cdi-readiness/cirros-readiness` |
| Punjab | `corral-vms/punjab` VM and VMI `Running`, ready on `karnataka`; guest tailnet IP `100.103.187.46` |

All services returned by inspection were ClusterIP services (including one
headless metrics service); none advertised a LoadBalancer or NodePort.
The inspected deployments and virt-handler DaemonSet were ready. This is a
single-node cluster, not an HA control plane: host or local-disk loss affects
both Kubernetes and Punjab. A bound PVC is not a backup.

The API listener is bound to `100.66.158.127:6443` and loopback, not all host
interfaces. The kubelet listener is `100.66.158.127:10250`. The serving
certificate inspected through the host included `100.66.158.127` and
`karnataka` as subject alternative names, was issued by the K3s server CA,
and expires 2027-10-27. Clients must use the embedded CA in the vault-backed
kubeconfig, not `--insecure-skip-tls-verify`. Tailscale routing and access
policy must permit each client to reach TCP 6443; merely reaching SSH does
not prove API connectivity. Do not publish the API or Corral on the Internet.

### Fleet client provisioning

The native [`kube` unit](../../../roles/kube.md) provisions the active cluster
on all active fleet computers, including servers, from the separate Bitwarden
secure note **`kubeconfig-karnataka-k3s`**. The note's standard notes field
contains a complete kubeconfig with cluster, user and context named
`karnataka-k3s`, the endpoint above, and embedded CA/client credentials.
Treat it as a secret; never print it or commit it.

With a valid Bitwarden session, use the normal fleet entry points:

```bash
just apply-tags packages,kube
# From the fleet controller, apply to each active reachable host:
just apply-remote HOST
```

The unit writes `~/.kube/config-karnataka-k3s` with mode `0600`, merges into
`~/.kube/config` without discarding historical contexts, and selects
`karnataka-k3s` on each apply. The first existing default config is backed up
once to `~/.kube/config-pre-karnataka-k3s`. An explicitly set `KUBECONFIG`
environment variable can override the default file; unset it or point to
the intended config before using these commands.

For production hosts where only client access is required, an operator can
securely preseed the standalone cache above and install `kubectl`, then run
the narrower cached-only path instead of applying unrelated fleet units:

```bash
KUBE_CACHED_ONLY=1 UNITS_NO_SECRETS=1 bash units/kube.sh
```

This mode merges/selects the cached context without invoking Bitwarden or
seeding recovery notes. Ordinary `--no-secrets` without this explicit mode
remains no-write; it does not provision a client.

Keep the historical home Talos `kubeconfig` / `talosconfig` Bitwarden notes
and their files, and the separate AWS recovery configs. They are not inputs
for this live cluster and must not be overwritten with K3s credentials.
The [Talos handbook](../cluster.md) describes historical recovery only;
its reinstall, reset, bootstrap and workload commands do not apply here.
The terminated [AWS Talos cluster](../../aws-k8s/cluster.md) is also separate.

### Verified client rollout (2026-10-29)

Punjab, Karnataka, Kerala and Spindle now use `karnataka-k3s` as their default
context. Each passed a real authenticated `/readyz` request and listed the
Ready `karnataka` node with normal CA verification. Config files are `0600`;
the rollout compared existing contexts, clusters and users to confirm they
were retained. Private pre-rollout copies are under each user's
`~/.local/state/dotfiles/k3s-rollout-20261029T021854Z/`.

Mumbai, Himachal, Dilli and Kanpur were unreachable during rollout. Termux
was on the tailnet but its configured SSH port 8022 refused connections.
Their repository policy/package changes are prepared, but those machines
have **not** received the live configuration; apply once they are reachable.
Retired `matrix` and `telengana` were not modified.

### Read-only client smoke commands

After provisioning and while connected to the tailnet, these commands read
cluster state without creating a pod, changing context or modifying resources:

```bash
kubectl --context karnataka-k3s get --raw=/readyz
kubectl --context karnataka-k3s get nodes -o wide
kubectl --context karnataka-k3s get deployments,daemonsets -A
kubectl --context karnataka-k3s get services -A
kubectl --context karnataka-k3s get storageclasses,persistentvolumes
kubectl --context karnataka-k3s get persistentvolumeclaims -A
kubectl --context karnataka-k3s get virtualmachines,virtualmachineinstances -n corral-vms
```

For an isolated check of the cached credentials rather than the merged file,
add `--kubeconfig "$HOME/.kube/config-karnataka-k3s"` to a command.
Do not use `kubectl config view --raw`, dump Secret objects, or paste
credentials into diagnostics. If the API is unavailable, retain SSH and
inspect `systemctl status k3s` before considering any repair or restart;
Punjab depends on this server.

## K3s operation

The host-specific files are in `home-k3s/`. The enabled, active systemd unit
is `/etc/systemd/system/k3s.service`, with
`ExecStart=/var/usrlocal/bin/k3s server`. It orders after
`network-online.target` and `tailscaled.service` and runs
`/var/usrlocal/libexec/k3s-wait-tailnet` before starting, then attempts to load
`br_netfilter` and `overlay`. The binary is pinned at
`/var/usrlocal/bin/k3s`. For read-only inspection on the host:

```bash
systemctl status k3s
sudo /var/usrlocal/bin/k3s kubectl --server https://100.66.158.127:6443 get pods -A
```

Reloading the service definition does not restart K3s. Do not restart it as
part of client provisioning.

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

Read-only inspection on 2026-10-29 found `tailscale0` unassigned to a
firewalld zone, so incoming API connections used default `public`. That zone
allowed SSH but not TCP 6443; firewalld rejected API connections despite
Tailscale's earlier input-chain acceptance. `home-k3s/firewall.sh` now manages
a scoped API rich rule in `public`, in both runtime and permanent stores:
IPv4 source `100.64.0.0/10`, destination `100.66.158.127/32`, TCP 6443 only.
This is separate from the pod-egress policy and does not open other host
services, change zone/interface assignments, reload firewalld or restart K3s.
Tailscale's existing anti-spoofing input rules reject that source range on
non-Tailscale interfaces; retain those rules.

The helper refuses changes if the default zone is no longer `public`, if
`tailscale0` is explicitly assigned elsewhere, or if any zone has source
bindings in either store (source classification can override interfaces).
Resolve such drift deliberately rather than opening another zone blindly.
`--check` requires the API rule in both stores; `--apply` checks it again
after changes. A successful firewall check is not proof of client API
connectivity: perform the read-only smoke commands above from each client.
The API rule was subsequently applied and verified in both stores, restoring
client API access without a reload. The full helper still returned nonzero
at the pre-existing absent runtime pod-egress policy described below; it was
not force-activated. This does not invalidate the separate API rule or the
authenticated client checks, and is not a claim that the full helper passed.

The broad `gateway-lan-to-world` baseline accepts traffic from `internal`,
`home` and `trusted` to both `public` and `external` and must not be enabled
unchanged. `home-k3s/firewall.sh` defines a dedicated `k3s-pod-egress` policy:
`internal` ingress, `public` egress, `CONTINUE`
target, and one IPv4 accept rule for source `10.42.0.0/16`. K3s supplies pod
masquerading; the policy does not alter NAT or host INPUT rules. It accepts all
protocols and ports from that CIDR, not just HTTPS: `public` includes the LAN
as well as Internet routes, so pods can reach LAN addresses. Source addresses
can be spoofed; this is not per-pod isolation. IPv6, other pod CIDRs and
non-`public` egress zones are not covered. Other firewalld/K3s rules may also
allow traffic; this policy is not a comprehensive egress firewall.

On 2026-10-28 the dedicated policy was staged in Karnataka's permanent store
without reloading firewalld. Its first activation on a real firewall restart
is unverified. In isolated firewalld 2.5.2 namespaces, staging, reload, and
`--check` succeeded; traffic from `10.42.0.2` forwarded while `10.43.0.2` did
not. `sudo bash home-k3s/firewall.sh --check` inspects both stores
without changes. `--apply` refuses foreign interface/source bindings and policy
drift instead of taking over a broader policy. Firewalld 2.5.2 can create a
policy only in the permanent store, so the first `--apply` stages it there but
returns nonzero while the policy is absent at runtime. It never reloads
firewalld. Interrupted creation may leave a partial policy; a later apply can
finish it. Other policies are not changed.

### Optional temporary runtime bridge

`home-k3s/firewall-egress-bridge.sh` provides a separate, opt-in bridge until
the dedicated permanent policy activates. On 2026-10-28 it was enabled on
Karnataka with its rollback timer armed; a new SSH session from Himachal and
pod HTTPS succeeded before the bridge was committed. The timer was stopped on
commit; its automatic rollback has not been exercised on the live host. The
bridge requires the exact observed disabled `gateway-lan-to-world`
baseline, `internal` containing only `cni0`, `internal` not being the default,
and **no source bindings in any zone in either store**. It narrows the runtime
policy to `internal` → `public`, adds negative-priority drops for non-pod IPv4
sources and all IPv6, and only then enables it. It does not modify the vendor
policy's permanent configuration or load the staged dedicated policy.

Unlike the dedicated policy's `CONTINUE` target, the temporary policy's target
is `ACCEPT`; the drop rules restrict that acceptance to `10.42.0.0/16` IPv4.
They can also drop traffic that a later policy would otherwise allow, and
earlier policies or established-connection handling may bypass them. Pod IPs
can be spoofed, all protocols and LAN destinations in `public` are allowed,
and this is not per-pod isolation. Inspect all other policies and both stores'
zone bindings as described below before considering it. A change to source
bindings or `internal` after activation invalidates the assumptions.

Only with console recovery, a retained Tailscale SSH session, and the systemd
timer probe below proven successful, run:

```bash
sudo bash home-k3s/firewall-egress-bridge.sh --apply
sudo bash home-k3s/firewall-egress-bridge.sh --status
```

The helper schedules and checks a 15-minute rollback timer before any firewall
mutation. It uses a root-owned snapshot under `/run/k3s-egress-bridge`; do not
remove it while the timer is armed. On a command failure it attempts immediate
rollback, leaving the timer armed to retry. The timer disables the gateway
policy first, removes only the two bridge rules, restores the original zone
membership, and checks the disabled baseline. If rollback cannot be verified,
use console recovery and inspect `journalctl -u
k3s-egress-bridge-rollback.service`; never reload firewalld to recover SSH.

While the timer remains armed, verify a **new** SSH connection and pod DNS and
HTTPS with the disposable pod command below. After those checks and before the
timer expires, an operator may explicitly stop automatic rollback:

```bash
sudo bash home-k3s/firewall-egress-bridge.sh --commit
sudo bash home-k3s/firewall-egress-bridge.sh --status
```

`--commit` verifies the active narrowed policy and bindings before stopping
the timer; it does not persist the bridge. To revert after committing or after
the timer fires, run `sudo bash home-k3s/firewall-egress-bridge.sh --cleanup`;
this restores and verifies the disabled baseline before stopping any timer.
If the timer has already fired, cleanup removes its managed state. On reboot
`/run` and this runtime-only bridge disappear; if the dedicated policy was
staged, it is then loaded from permanent configuration and must be checked
separately with `firewall.sh --check`.

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
