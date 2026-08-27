# Backups — AWS Talos cluster

Two independent layers, because they fail differently and cover different
disasters.

| Layer | What | Covers | Does not cover |
|---|---|---|---|
| **Postgres dumps** | `postgres-backup.yaml` — nightly 02:17 UTC, 7 days on a local PVC | dropped tables, bad migrations, logical corruption | losing the node |
| **EBS snapshots** | DLM `policy-0f074c7d13f94e355` — daily 03:30 UTC (7) + weekly Sun (4) | node loss, volume loss, whole-cluster rebuild | fine-grained "undo this one table" |

The snapshot window is deliberately *after* the dump window, so each snapshot
also captures that night's fresh dump.

## What is actually protected

Everything on the cluster lives on `local-path`, i.e. the nodes' root EBS
volumes — so the snapshots cover all of it:

- `postgres/pgdata` — Synapse (14GB) + MAS
- `postgres/pg-backups` — the nightly logical dumps
- `ess/synapse-media-preseed` — user media, 4.6GB, **irreplaceable and in no
  database**
- `hive/hive-data` — 17GB of agent state, sessions, audit log
- `default/review-data`, `hive/discord-reports-data`

Both root volumes carry the tag `Backup=fleet-daily`, which is how DLM selects
them. **A new volume is not backed up until it has that tag** — DLM targets by
tag, not by instance.

## Verifying — do not assume

The predecessor to this system wrote 0-byte dumps nightly for three weeks
without anyone noticing, so treat "it exists" as meaningless.

```bash
# Snapshots actually completing?
aws ec2 describe-snapshots --owner-ids self --region eu-north-1 \
  --query 'reverse(sort_by(Snapshots,&StartTime))[:5].[SnapshotId,State,Progress,StartTime]' \
  --output text

# DLM policy still enabled and not erroring?
aws dlm get-lifecycle-policy --policy-id policy-0f074c7d13f94e355 --region eu-north-1 \
  --query 'Policy.[State,StatusMessage]' --output text

# Dumps present, and do they parse?
kubectl -n postgres exec deploy/postgres -- ls -la /backups/ 2>/dev/null
```

The dump job proves each archive with `pg_restore --list` and enforces a size
floor; a **staleness CronJob** alerts if the newest dump is older than 36h,
because a job that never runs emits no error.

## Restoring

**Logical (preferred for data mistakes)** — dumps are `pg_dump -Fc`:

```bash
kubectl -n postgres exec -it deploy/postgres -- \
  pg_restore -U postgres -d synapse --clean --if-exists /backups/<date>/synapse.dump
```
Scale Synapse to zero first; it will not tolerate the schema moving underneath it.

**Volume (for node loss)** — create a volume from the snapshot, attach it to a
replacement node, and let Talos boot from it. Note `local-path` PVs carry node
affinity: restoring onto a differently-named node needs the PV's
`nodeAffinity` patched, or the data moved into a freshly-provisioned PVC.

## Alerting

Discord is primary; ntfy is best-effort secondary. ntfy.sh was tried first and
rejected — it returned 502 on all three retries during a real run and then went
unreachable entirely. An alert channel that silently drops messages is worse
than none. If neither channel delivers, the job logs a warning rather than
exiting quietly.

## Known gaps

- Snapshots are **crash-consistent**, not application-consistent. That is fine
  for Postgres (it replays WAL on start) and is why the logical dumps exist
  alongside them.
- Everything is in `eu-north-1`. A region loss takes both layers. Cross-region
  snapshot copy is a one-line DLM addition if that ever matters.
- No restore drill has been performed. Until a dump has actually been restored
  into a scratch database, "restorable" is an assumption — a good one, since
  every archive is parsed by `pg_restore --list`, but still an assumption.
