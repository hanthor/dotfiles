# AWS Talos Cluster

> **TunaOS infrastructure.** This runs in the TunaOS AWS account and serves
> the TunaOS project (Hive, Matrix, CI), not James's personal fleet. See
> [TunaOS AWS Account & IaC](../aws/README.md).

Two-node Talos Kubernetes cluster in AWS `eu-north-1`, built 2026-08-27 to
consolidate the two Hetzner VPSes (`matrix` and `telengana`) onto one cluster.

All AWS resources here (VPC, security groups, nodes, Elastic IPs, volumes, snapshot policy) are
codified in OpenTofu under [`aws/`](https://github.com/hanthor/dotfiles/tree/master/aws).
See [AWS Account](../aws/README.md). Node *configuration* is not; that is
`talosctl`'s job.

Like the home cluster, these nodes are **talosctl/kubectl-managed only** — Talos
has no SSH, no package manager, and an immutable root. They are deliberately
*not* in `inventory.yml` and no Ansible role targets them.

## Nodes

| Role | Instance | Labels |
|------|----------|--------|
| control-plane | `m6i.xlarge` | `workload-role=hive` |
| worker | `m6i.xlarge` | `workload-role=matrix` |

Each node has a private VPC address and an Elastic IP; the addresses live in
the OpenTofu state and the talosconfig, not here.

Talos `v1.13.9`, Kubernetes `v1.36.2`, flannel CNI, `local-path` storage.

The control-plane taint is removed so it schedules workloads too. `m6a` (AMD) is
**not offered in `eu-north-1`** — `m6i` is the equivalent.

## Network

Dedicated VPC `10.20.0.0/16`, single AZ `eu-north-1a`, public subnet + IGW, no
NAT gateway (unnecessary, and ~$32/mo).

Three security groups:

| Security group | Purpose |
|---|---|
| intra-cluster | self-referencing, node-to-node traffic |
| public | web ingress, Matrix federation, and the MatrixRTC media ports |
| admin | Talos and Kubernetes APIs, admin allowlist only |

Both nodes carry the public group, so either node can serve web traffic. The
RTC ports match what the ESS chart's MatrixRTC SFU exposes as NodePorts.

> The admin allowlist **will go stale**. It lives in `aws/terraform.tfvars`
> (Bitwarden `aws-tofu-tfvars`). Update it with `just aws-apply`, not in the
> console. The long-term fix is a Tailscale subnet router in-cluster rather
> than widening the CIDR.

## Ingress — the important gotcha

The Traefik `Service` is `type: LoadBalancer` and stays **`<pending>` forever**:
Talos on EC2 has no cloud-controller-manager, so nothing provisions an ELB.
Public traffic works only because the Traefik pod binds **hostPorts 80/443**.

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

DNS points only at the worker's Elastic IP.

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

Lesson: hive cannot move to the worker (its PVC is `local-path` and node-bound),
so the control-plane must be sized for it. Ingress HA on both nodes only becomes
viable with that headroom.

## Workloads

| Namespace | What | Exposure |
|---|---|---|
| `ess` | Matrix (Synapse + workers, MAS, MatrixRTC, haproxy, redis, element-admin) | `matrix`/`auth`/`call`/`matrixadmin.reilly.asia` |
| `hive` | tuna-os Hive (SCHOOL) + Discord bots | `school.tunaos.org` (legacy alias `hive.tunaos.org`), Cloudflare-proxied |
| `hive-reef` | tuna-os Hive (REEF) | `reef.tunaos.org` |
| `hive-hub` | Hive hub — every Hive's status in one place | `hub.tunaos.org` |
| `postgres` | Postgres 16 — **the production DB** for Synapse + MAS | in-cluster only |
| `default` | CFP review dashboard, searxng | Tailscale ingress |
| `cert-manager` | Let's Encrypt via Cloudflare DNS-01 | — |
| `tailscale` | Tailscale operator (ingress proxies) | — |

### Postgres is in-cluster, by necessity

The original plan put Postgres on the host. Talos makes that impossible — there
is no host to install packages on. The k8s-deployed Postgres in the `postgres`
namespace **is** production.

That means DB durability currently rests on `local-path` on the worker's root
volume. The separate 50GB gp3 pgdata volume is attached at
the EC2 level but **not mounted by Talos** — unfinished work.

## Access

`kubectl`/`talosctl` need **`endpoints` = public EIP, `nodes` = private IP** —
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

Configs live in Bitwarden as `kubeconfig-aws-migration` / `talosconfig-aws-migration`
and are fetched by the [`kube`](../../roles/kube.md) role into
`~/.kube/config-aws-migration` and `~/.talos/config-aws-migration` — kept
separate from the home cluster's files so both stay independently usable.

## Cost

Covered by permanent AWS credits ($1400/mo). An AWS Budget
(`migration-monthly-spend`) alerts at $150 / $500 / $1400. No Savings Plan —
credits zero the bill, so a commitment buys nothing and locks in instance shape.

## Known gaps

- 50GB Postgres volume unmounted (above).
- ~~Backups partial~~ — done 2026-09-24: nightly Postgres dumps are copied to
  S3 (the fleet-backups bucket, `postgres/`) and size-verified, and DLM
  snapshots both root volumes. See [`talos-k8s/backup/`](https://github.com/hanthor/dotfiles/tree/master/talos-k8s/backup).
- API-server OIDC + finer-grained RBAC still deferred; access is a single admin
  client cert.

## See also

- [Matrix cutover runbook](https://github.com/hanthor/dotfiles/blob/master/docs/matrix-cutover-runbook.md)
- [`hive_ops` role](../../roles/hive_ops.md)
