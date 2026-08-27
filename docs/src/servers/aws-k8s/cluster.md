# AWS Talos Cluster

Two-node Talos Kubernetes cluster in AWS `eu-north-1`, built 2026-08-27 to
consolidate the two Hetzner VPSes (`matrix` and `telengana`) onto one cluster.

Like the home cluster, these nodes are **talosctl/kubectl-managed only** — Talos
has no SSH, no package manager, and an immutable root. They are deliberately
*not* in `inventory.yml` and no Ansible role targets them.

## Nodes

| Role | Instance | Private | Elastic IP | Labels |
|------|----------|---------|------------|--------|
| control-plane | `m6i.large` | `10.20.1.10` | `13.63.243.56` | `workload-role=hive` |
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
Public traffic works only because the Traefik *Deployment* binds **hostPorts
80/443** on whichever node it runs.

Consequences:

- Traefik runs on the **control-plane** node, so all public DNS points at
  `13.63.243.56` — not the worker, despite the worker holding the ESS pods.
- Traefik is pinned with `nodeSelector: kubernetes.io/hostname=ip-10-20-1-10`
  and `strategy: Recreate`. A RollingUpdate **cannot** work with hostPorts —
  the new pod can't bind ports the old one still holds and hangs `Pending`.
- **That pin is a live `kubectl patch`, not in the Traefik Helm values.** A
  `helm upgrade` of Traefik will revert it. Fold it into the release values, or
  convert Traefik to a DaemonSet so both node IPs serve (also removes the SPOF).

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

- Traefik pin is not in Helm values (above).
- 50GB Postgres volume unmounted (above).
- No backups yet — no EBS snapshot lifecycle, no `pg_dump` to S3. The old box's
  nightly dumps had been silently producing 0-byte files since ~Aug 5, so this
  is a **pre-existing** gap that followed the data across, not a new one.
- API-server OIDC + finer-grained RBAC still deferred; access is a single admin
  client cert.

## See also

- [Matrix cutover runbook](../../../matrix-cutover-runbook.md)
- [`hive_ops` role](../../roles/hive_ops.md)
