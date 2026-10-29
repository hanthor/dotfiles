# Matrix

> **Retired 2026-08-27.** The Matrix homeserver moved first to the
> [AWS Talos cluster](../../servers/aws-k8s/cluster.md), terminated 2026-10-25,
> and now runs on the [OCI VPS](../../servers/spindle-vps/README.md). Restart
> nothing on this retired host; the page below is historical. See the
> [Matrix cutover runbook](https://github.com/hanthor/dotfiles/blob/master/docs/matrix-cutover-runbook.md).

Former VPS node in the fleet (`vps` group in `inventory.yml`) that hosted the
`reilly.asia` Matrix homeserver.

## What it ran

- Ubuntu 24.04 LTS, x86_64
- [Synapse](https://github.com/element-hq/synapse) + MAS on a single-node
  [Kubernetes](https://kubernetes.io/) install, with
  [PostgreSQL](https://www.postgresql.org/) as the database
- Previously managed by the fleet playbook (daily cron apply, no secrets/homebrew)

## Retirement

Synapse and MAS were scaled to zero at cutover and must stay that way: two live
homeservers sharing one federation identity is unrecoverable. Automatic
upgrades on the box were disabled so nothing resurrects them.

## Lessons carried forward

- A single VPS with no swap and unmanaged journald growth was fragile for K8s;
  the former AWS cluster needed more headroom (see the OOM incident in its
  [archived handbook](../../servers/aws-k8s/cluster.md)).
- `reilly.asia` DNS is on [Cloudflare](https://www.cloudflare.com/), which made
  the cutover a DNS change rather than a server move.
