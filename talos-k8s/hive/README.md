# Hive fleet on the AWS Talos cluster

Three [hivecommons/hive](https://github.com/hivecommons/hive) spokes plus the
hub, all on upstream **v6** (`ghcr.io/hivecommons/hive:v6-latest`, pinned by
digest). `KUBECONFIG=~/.kube/config-aws-migration`.

| Spoke | Namespace | Hostname | Org |
|---|---|---|---|
| school (primary) | `hive` | school.tunaos.org (alias hive.tunaos.org) | tuna-os |
| reef | `hive-reef` | reef.tunaos.org | tuna-os (shares school's App installation) |
| hanthor | `hive-hanthor` | hive.reilly.asia | hanthor |
| hub | `hive-hub` | hub.tunaos.org | — |

## Who manages what

The goal is one control plane: the **[hive-operator](https://github.com/tuna-os/hive-operator)**
(ns `hive-system`). Each responsibility moves from a bash CronJob to an
operator controller in a single change that promotes the controller to
`Enforce` **and** deletes the CronJob. Two writers on one field is how the
fleet got rolled back to v5 every night.

| Responsibility | Owner today | Target |
|---|---|---|
| Image version / upgrades | **operator** — `HiveRelease hive`, Enforce since 2026-10-01 (`hive-upgrade` deleted) | done |
| Backend/model rotation, stranding, auto-resume | `hive-rotate*` CronJobs | `HiveSpoke` rotation (Shadow now) |
| Quota / credit starvation, pacing | `hive-pace`, ccleft | `UsagePool` + rotation pacer |
| Liveness (watchdog, nudge) | `hive-watchdog*`, `hive-nudge` | operator watchdog |
| Shared auth store | `hive-shared-auth` | `SharedAuth` (Shadow now) |
| Housekeeping (tiers, inventory, pi-kiro, cli-update, repo-sync, metrics, activity) | CronJobs in [`ops/`](ops/README.md) | CronJobs owned by the operator |

Check where each stands before changing anything:

```bash
kubectl get hivespokes,modelladders,sharedauths,hivereleases
kubectl -n hive get cronjobs
```

## Layout

- [`spokes/`](spokes/): each spoke's Deployment, Service, Ingress, config
  ConfigMaps and PVCs, exported from the cluster. Secrets are created out of
  band and are not in git. **The `hive` container image in these files is not
  authoritative**: the operator owns it. Applying a file with an older image
  is a rollback.
- [`ops/`](ops/README.md): the bash CronJobs and their scripts. They shrink as
  the operator takes over.
- [`upgrade/`](upgrade/README.md): the retired `hive-upgrade` script, kept for
  reference. Its CronJob is deleted; the `HiveRelease` controller replaced it
  (tracks `v6-latest` by digest, rolls hanthor → reef → school in the
  04:30–06:30 New York window with soak and rollback).
- [`ccleft/`](ccleft/README.md): remaining-quota readings for every account.
- [`discord/`](discord/README.md), [`kiro/`](kiro/): integrations.
- [`history/`](history/): the v2 (goose/DeepSeek) era docs and handoffs.

## Auth

Automation authenticates with the spoke's dashboard token (Secret
`hive-secrets`, key `HIVE_DASHBOARD_TOKEN`) in the `X-Hive-Internal` header,
against the pod's `:3002`. On v6 that is owner-equivalent when no session
cookie accompanies it (hivecommons/hive#4134), so pause, resume, kick and
`PUT /api/config/agent/{name}/models` need no browser login. Browsers still
sign in with GitHub device flow.

## Changing an agent's model

Through the API, never by editing `hive-config`: the ACMM pack re-asserts
defaults on restart unless a field is operator-owned, and the models PUT marks
it so. While rotation is still bash-owned, a pin must also be added to the
rotate CronJob's `HIVE_ROTATE_PIN` or rotation will move the agent again.
