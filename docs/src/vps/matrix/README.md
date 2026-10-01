# Matrix

> **Retired 2026-08-27.** The Matrix homeserver was migrated to the
> [AWS Talos cluster](../../servers/aws-k8s/cluster.md). See the
> [Matrix cutover runbook](https://github.com/hanthor/dotfiles/blob/master/docs/matrix-cutover-runbook.md)
> before touching anything that was on this box. The page below is historical.

Former VPS node in the fleet (`vps` group in `inventory.yml`) that hosted the
`reilly.asia` Matrix homeserver.

## What it ran

- Ubuntu 24.04 LTS, x86_64
- [Synapse](https://github.com/element-hq/synapse) + MAS on a single-node
  [Kubernetes](https://kubernetes.io/) install, with
  [PostgreSQL](https://www.postgresql.org/) as the database
- Managed by the fleet playbook (daily cron apply, no secrets/homebrew)

## Retirement

Synapse and MAS were scaled to zero at cutover and must stay that way: two live
homeservers sharing one federation identity is unrecoverable. Automatic
upgrades on the box were disabled so nothing resurrects them.

## Lessons carried forward

- A single VPS with no swap and unmanaged journald growth was fragile for K8s;
  the AWS cluster sizes nodes for their workloads instead (see the OOM incident
  in the [AWS cluster handbook](../../servers/aws-k8s/cluster.md)).
- `reilly.asia` DNS is on [Cloudflare](https://www.cloudflare.com/), which made
  the cutover a DNS change rather than a server move.
