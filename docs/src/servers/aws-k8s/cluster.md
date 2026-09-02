# AWS Talos Cluster

Two-node Talos Kubernetes cluster in AWS `eu-north-1`, built 2026-08-27 to
consolidate the two Hetzner VPSes (`matrix` and `telengana`) onto one cluster.

Like the home cluster, these nodes are **talosctl/kubectl-managed only** — Talos
has no SSH, no package manager, and an immutable root. They are deliberately
*not* in `inventory.yml` and no Ansible role targets them.

## Nodes

| Role | Instance | Private | Elastic IP | Labels |
|------|----------|---------|------------|--------|
| control-plane | `m6i.xlarge` | `10.20.1.10` | `13.63.243.56` | `workload-role=hive` |
| worker | `m6i.xlarge` | `10.20.1.11` | `13.62.161.5` | `workload-role=matrix` |

Talos `v1.13.9`, Kubernetes `v1.36.2`, flannel CNI, `local-path` storage.

The control-plane taint is removed so it schedules workloads too. `m6a` (AMD) is
**not offered in `eu-north-1`** — `m6i` is the equivalent.

## Network

Dedicated VPC `10.20.0.0/16`, single AZ `eu-north-1a`, public subnet + IGW, no
NAT gateway (unnecessary, and ~$32/mo).

| Security group | Rules |
|---|---|
| `migration-intracluster` | self-referencing, all traffic |
| `migration-matrix-public` | 80, 443, 8448/tcp · 30001/tcp · 30002/udp · 32700-32767/udp |
| `migration-admin-bootstrap` | Talos API 50000 + k8s API 6443, admin IP only |

Both nodes carry `migration-matrix-public`, so either public IP serves 80/443.
The RTC ports match what the ESS chart's MatrixRTC SFU exposes as NodePorts.

> The admin IP allowlist **will go stale**. The long-term fix is a Tailscale
> subnet router in-cluster rather than widening the CIDR.

## Ingress — the important gotcha

The Traefik `Service` is `type: LoadBalancer` and stays **`<pending>` forever**:
Talos on EC2 has no cloud-controller-manager, so nothing provisions an ELB.
Public traffic works only because the Traefik pod binds **hostPorts 80/443**.

Driven from [`talos-k8s/traefik/values.yaml`](../../../../talos-k8s/traefik/values.yaml).
Three non-obvious settings, all load-bearing:

- **`deployment.kind: DaemonSet`.** A single-replica Deployment is a SPOF whose
  rescheduling silently kills all ingress.
- **`maxSurge: 0 / maxUnavailable: 1`.** hostPorts make the chart default
  (surge-then-delete) impossible — the new pod can never bind ports the old one
  still holds, so rollouts hang with the replacement `Pending` forever. Costs a
  few seconds of downtime per Traefik upgrade.
- **`nodeSelector: workload-role=matrix`.** Running Traefik on *every* node was
  tried and reverted — see the incident note below.

DNS points only at the worker EIP `13.62.161.5`.

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
| `hive` | tuna-os Hive + Discord realtime | `hive.tunaos.org` (Cloudflare-proxied) |
| `postgres` | Postgres 16 — **the production DB** for Synapse + MAS | in-cluster only |
| `default` | CFP review dashboard, searxng | Tailscale ingress |
| `cert-manager` | Let's Encrypt via Cloudflare DNS-01 | — |
| `tailscale` | Tailscale operator (ingress proxies) | — |

### Postgres is in-cluster, by necessity

The original plan put Postgres on the host. Talos makes that impossible — there
is no host to install packages on. The k8s-deployed Postgres in the `postgres`
namespace **is** production.

That means DB durability currently rests on `local-path` on the worker's root
volume. The separate 50GB gp3 volume (`vol-01ff00a316340f0ad`) is attached at
the EC2 level but **not mounted by Talos** — unfinished work.

## Access & Context Management

`kubectl`/`talosctl` need **`endpoints` = public EIP, `nodes` = private IP** —
not the same address for both. Talos does a two-hop call (client → endpoint →
node); pointing both at the public EIP makes the node try to reach *itself* via
its own Elastic IP from inside the VPC, which AWS's hairpin NAT does not
support. The symptom is a maximally confusing `dial tcp …: i/o timeout` that
looks like a raw network fault.

### Unified Fleet Access

The `kube` Ansible role syncs both cluster configurations from Bitwarden and automatically merges them into a unified **`~/.kube/config`** and **`~/.talos/config`** on any desktop in the fleet:

- **Context Names:**
  - `admin@aws-migration` (AWS Talos cluster — active)
  - `admin@talos-k8s` (Home metal cluster — offline in storage)

```bash
# Switch to AWS cluster
kubectl config use-context admin@aws-migration
talosctl config context aws-migration

# Run commands
kubectl get nodes -o wide
kubectl get pods -A
```

Standalone files (`~/.kube/config-aws-migration` and `~/.talos/config-aws-migration`) remain available for legacy scripts and explicit environment overrides (`KUBECONFIG=~/.kube/config-aws-migration`).

### Preferred: kubectl over Tailscale (no security-group changes)

The Tailscale **operator** in the `tailscale` namespace runs the built-in
**Kubernetes API server proxy** (`apiServerProxyConfig.mode: "true"`, enabled
2026-09-01). It serves the API on the tailnet at
`https://aws-migration-operator.manatee-basking.ts.net` with a valid tailnet
TLS cert, so any tailnet device reaches the API with **no `:6443`
security-group hole**. This is the preferred path.

```bash
# One-time: add a kubeconfig context that uses the operator auth proxy.
KUBECONFIG=~/.kube/config-aws-migration \
  tailscale configure kubeconfig aws-migration-operator
kubectl config use-context aws-migration-operator.manatee-basking.ts.net
kubectl get nodes
```

Auth mode: the proxy authenticates the caller as their **tailnet identity**
(e.g. `jreilly1821@gmail.com`) and RBAC is enforced in-cluster. A
`ClusterRoleBinding` (`tailscale-admin-jreilly`) binds that user to
`cluster-admin`. To grant another tailnet user, bind their identity the same
way. The operator Helm release carries the proxy setting:

```bash
helm -n tailscale get values tailscale-operator   # apiServerProxyConfig.mode: "true"
```

### Fallback: Admin Security Group Authorizations

When Tailscale is unavailable, direct access to the k8s API (`:6443`) and Talos
API (`:50000`) is protected by EC2 Security Group
**`migration-admin-bootstrap`** (`sg-052a6292d2dcf728e`) in `eu-north-1`.

When your public IP changes, update the security group using the `james-admin` AWS profile:

```bash
MY_IP=$(curl -s https://api.ipify.org)
AWS_PROFILE=james-admin aws ec2 authorize-security-group-ingress \
  --region eu-north-1 --group-id sg-052a6292d2dcf728e \
  --protocol tcp --port 6443 --cidr "${MY_IP}/32"
AWS_PROFILE=james-admin aws ec2 authorize-security-group-ingress \
  --region eu-north-1 --group-id sg-052a6292d2dcf728e \
  --protocol tcp --port 50000 --cidr "${MY_IP}/32"
```

## Cost

Covered by permanent AWS credits ($1400/mo). An AWS Budget
(`migration-monthly-spend`) alerts at $150 / $500 / $1400. No Savings Plan —
credits zero the bill, so a commitment buys nothing and locks in instance shape.

## Known gaps

- Traefik pin is not in Helm values (above).
- 50GB Postgres volume unmounted (above).
- **Backups are partial.** Postgres now has verified nightly dumps —
  see [`talos-k8s/backup/postgres-backup.yaml`](../../../../talos-k8s/backup/postgres-backup.yaml)
  — but they land on a **local-path PVC on the same node as the database**.
  That protects against dropped tables and bad migrations, *not* against losing
  the node. `ess-synapse-media` (4.6GB) and `hive-data` (17GB) have **no backup
  at all**. Off-cluster copies are blocked: `james-admin` has neither `dlm:*`
  (managed EBS snapshots) nor IAM permissions (to mint a scoped S3 writer for an
  in-cluster job). Granting those two is the unblock.
- API-server OIDC + finer-grained RBAC still deferred; access is a single admin
  client cert.

## See also

- [Matrix cutover runbook](../../../matrix-cutover-runbook.md)
- [`hive_ops` role](../../roles/hive_ops.md)
- [`kube` role](../../roles/kube.md)
- [Talos K8s Metal Cluster (offline)](../talos-k8s/cluster.md)

