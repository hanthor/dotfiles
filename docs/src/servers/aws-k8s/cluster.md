# AWS Talos Cluster (archive)

> **Terminated 2026-10-25.** This is a historical record, not an operating
> runbook. The fleet-backups S3 bucket and a mirror on himachal-1
> (`~/backups/tunaos-aws-2026-10-25`) were retained; the current status of
> individual volumes, snapshots, IPs and other AWS resources is not established
> here. Matrix and standalone LiveKit are deployed on the
> [OCI spindle VPS](../spindle-vps/README.md).
>
> **OpenTofu still describes removed cluster resources.** `just aws-plan` may
> propose recreating them, and `just aws-apply` can recreate infrastructure and
> incur costs. Review live state and every proposed action before applying; see
> [AWS account and IaC](../aws/README.md).

The following describes the former TunaOS two-node Talos Kubernetes cluster in
AWS `eu-north-1`, built 2026-08-27 to consolidate the two Hetzner VPSes
(`matrix` and `telengana`). Those retired hosts must not be restarted. The home
Talos cluster is separately powered down in storage and expected back.

Historical descriptions and commands below refer to the cluster as it existed
before termination; they cannot be used to access it now. The nodes were not
in `inventory.yml` and no Ansible role targeted them.

## Nodes

| Role | Instance | Labels |
|------|----------|--------|
| control-plane | `m6i.2xlarge` (8 vCPU / 32 GiB) | `workload-role=hive` |
| worker | `m6i.xlarge` | `workload-role=matrix` |

Each node had a private VPC address and an Elastic IP; addresses were recorded
in OpenTofu state and talosconfig.

Talos `v1.13.9`, Kubernetes `v1.36.2`, flannel CNI, `local-path` storage.

The control-plane taint was removed so it could schedule workloads too. `m6a`
(AMD) was not offered in `eu-north-1`; `m6i` was the equivalent.

## Network

Dedicated VPC `10.20.0.0/16`, single AZ `eu-north-1a`, public subnet + IGW, no
NAT gateway.

Three security groups:

| Security group | Purpose |
|---|---|
| intra-cluster | self-referencing, node-to-node traffic |
| public | web ingress, Matrix federation, and the MatrixRTC media ports |
| admin | Talos and Kubernetes APIs, admin allowlist only |

Both nodes carried the public group, allowing either to serve web traffic. The
RTC ports matched what the ESS chart's MatrixRTC SFU exposed as NodePorts.
The admin allowlist was in `aws/terraform.tfvars` (Bitwarden `aws-tofu-tfvars`).

## Ingress — the important gotcha

The Traefik `Service` was `type: LoadBalancer` and remained **`<pending>`**:
Talos on EC2 had no cloud-controller-manager to provision an ELB. Public traffic
worked because the Traefik pod bound **hostPorts 80/443**.

Driven from [`talos-k8s/traefik/values.yaml`](https://github.com/hanthor/dotfiles/blob/master/talos-k8s/traefik/values.yaml).
Three non-obvious settings, all load-bearing:

- **`deployment.kind: DaemonSet`.** A single-replica Deployment is a SPOF whose
  rescheduling silently kills all ingress.
- **`maxSurge: 0 / maxUnavailable: 1`.** hostPorts make the chart default
  (surge-then-delete) impossible — the new pod can never bind ports the old one
  still holds, so rollouts hang with the replacement `Pending` forever. Costs a
  few seconds of downtime per Traefik upgrade.
- **`nodeSelector: workload-role=matrix`.** Running Traefik on *every* node was
  tried and reverted — see the incident note below.

DNS pointed at the worker's Elastic IP at the time.

### Incident 2026-08-27: don't put workloads on an undersized control-plane

Running Traefik on both nodes tipped the control-plane over. Root cause was not
Traefik: the node was an `m6i.large` (7.7Gi) running etcd, the API server *and*
hive, whose agy/codex agent processes had grown into a 4Gi limit. Free memory
hit ~650Mi and **kube-scheduler and kube-controller-manager were OOM-killed**
(exit 137).

That deadlocks the cluster in a way that resists the obvious fix: with no
scheduler nothing can be placed, and `kubectl scale` cannot relieve the pressure
because actioning a scale-down is the controller-manager's job — and it was dead
too. The scale-to-zero appeared to succeed and did nothing. Recovery required
force-deleting the hive pods so the kubelet released memory.

Fixed properly by resizing the control-plane to `m6i.xlarge` (15.7Gi) — free
memory went from ~650Mi to ~12Gi — and keeping an explicit memory limit on hive
so the kubelet evicts *hive*, never the control plane.

**2026-09-24: resized again to `m6i.2xlarge`.** Three Hives on the control
plane pushed `m6i.xlarge` to a load of about 85 on 4 vCPU. Every `kubectl
exec` took 10–35 s, the ops CronJobs hung until their deadlines, and agents
were slow to reach a ready prompt. The in-place resize through OpenTofu took
about 3 minutes of Hive downtime; Matrix on the worker stayed up.

The node-bound `local-path` PVC prevented hive from moving to the worker, so
the control-plane needed enough headroom for its workloads.

## Former workloads

| Namespace | What | Exposure |
|---|---|---|
| `ess` | Matrix (Synapse + workers, MAS, MatrixRTC, haproxy, redis, element-admin) | `matrix`/`auth`/`call`/`matrixadmin.reilly.asia` |
| `hive` | tuna-os Hive (SCHOOL) + Discord bots | `school.tunaos.org` (legacy alias `hive.tunaos.org`), Cloudflare-proxied |
| `hive-reef` | tuna-os Hive (REEF) | `reef.tunaos.org` |
| `hive-hub` | Hive hub — every Hive's status in one place | `hub.tunaos.org` |
| `postgres` | Postgres 16 — former production DB for Synapse + MAS | in-cluster only |
| `default` | CFP review dashboard, searxng | Tailscale ingress |
| `cert-manager` | Let's Encrypt via Cloudflare DNS-01 | — |
| `tailscale` | Tailscale operator (ingress proxies) | — |

### Former Postgres storage

Talos made the original plan to install Postgres on the host impossible. The
cluster's production Postgres ran in the `postgres` namespace, with durability
depending on `local-path` on the worker's root volume. A separate 50GB gp3
pgdata volume was attached at the EC2 level but not mounted by Talos.

## Historical access

The old cluster is no longer reachable. Its `kubectl`/`talosctl` setup required
**`endpoints` = public EIP, `nodes` = private IP** —
not the same address for both. Talos does a two-hop call (client → endpoint →
node); pointing both at the public EIP makes the node try to reach *itself* via
its own Elastic IP from inside the VPC, which AWS's hairpin NAT does not
support. The symptom is a maximally confusing `dial tcp …: i/o timeout` that
looks like a raw network fault.

```bash
export KUBECONFIG=~/.kube/config-aws-migration
kubectl get nodes -o wide

# talosctl: endpoint = public EIP, node = private IP
talosctl --talosconfig ~/.talos/config-aws-migration \
  -e <node-eip> -n <node-private-ip> version
```

The configs were stored in Bitwarden as `kubeconfig-aws-migration` /
`talosconfig-aws-migration`; the [`kube`](../../roles/kube.md) unit still
fetches them into `~/.kube/config-aws-migration` and
`~/.talos/config-aws-migration` separately from the home cluster's files. They
no longer provide access to this terminated cluster.

## Historical cost context

The initial deployment used AWS credits, which have since been exhausted.
See [AWS account costs](../aws/README.md) for the current caution.

## Historical gaps

- The 50GB Postgres volume was unmounted.
- Nightly Postgres dumps were copied to S3 and size-verified; DLM snapshot
  schedules covered the root volumes. Retention of individual snapshots is not
  established by this historical record.
- API-server OIDC and finer-grained RBAC were deferred; access used an admin
  client certificate.

## See also

- [Matrix cutover runbook](https://github.com/hanthor/dotfiles/blob/master/docs/matrix-cutover-runbook.md)
- [`hive-ops` unit](../../roles/hive_ops.md)
