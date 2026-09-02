# Hive operations control plane

Everything that keeps the tuna-os Hive healthy — backend rotation, agent
liveness healing, provider-headroom probing, peak-window scheduling,
contributor lifecycle, repo sync, and the console's activity chart — runs as
**CronJobs in the `hive` namespace** of the AWS Talos cluster.

It used to run as systemd user timers on `himachal`. It does not any more, and
re-adding those timers while the CronJobs are active would be actively harmful.
See [Do not run two control planes](#do-not-run-two-control-planes).

| Where | What |
|---|---|
| `talos-k8s/hive-ops/hive-ops.yaml` | ServiceAccount, RBAC, state PVC, 8 CronJobs |
| `talos-k8s/hive-ops/deploy.sh` | publishes the scripts as a ConfigMap + applies the manifests |
| `roles/hive_ops/files/bin/*.sh` | the scripts themselves — **canonical home, edit here** |
| RFC | [tuna-os/hive#15](https://github.com/tuna-os/hive/issues/15) |

## Why it moved

Two failures, both caused purely by the control plane living on a desktop:

- Two agents sat in `PaneShowsLogin` for **43 hours** with 766 items queued.
  The hive detected it correctly the whole time; nothing was running to act.
- Rotation state lived in `~/.local/state/hive-rotate/` while the state it
  described lived in the cluster. When the `stranded` journal was lost, **8
  agents stayed paused on healthy providers** with nothing left that knew to
  free them. Every dashboard said they were fine.

## The jobs

| CronJob | Schedule | Does |
|---|---|---|
| `hive-watchdog` | `*/5 * * * *` | classify every agent pane; heal wedged/auth-broken ones; repair unlaunchable backend/model pairs; normalise shared-home permissions |
| `hive-rotate` | `*/20 * * * *` | probe all providers, place agents on the best available rung, un-strand recovered ones, reconcile contributor replicas |
| `hive-pace` | `5,25,45 * * * *` | burn-rate pacing: spend each pool so it lands empty at its reset, not before |
| `hive-peak-pause` | `0 1,6 * * 1-5` | pause agents on peak-priced providers |
| `hive-peak-resume` | `0 4,10 * * 1-5` | resume them |
| `hive-repo-sync` | `17 3 * * *` | add newly created tuna-os repos to hive's managed list |
| `hive-metrics` | `23 * * * *` | publish the bot's daily PR/issue counts for the console chart |
| `hive-fork-drift` | `41 4 * * *` | alert when the fork is fully absorbed upstream |
| `hive-tiers` | `30 4 * * 1` | refresh the capability-tier table |

All use `concurrencyPolicy: Forbid`. This is not optional — `/api/status` lags a
mutation by more than 10s, so a second concurrent pass decides on pre-mutation
state.

## Operating it

```bash
export KUBECONFIG=~/.kube/config-aws-migration

kubectl get cronjob -n hive -l app.kubernetes.io/name=hive-ops
kubectl logs -n hive -l app.kubernetes.io/component=rotate --tail=50
kubectl logs -n hive -l app.kubernetes.io/component=watchdog --tail=50

# run one now
kubectl create job -n hive adhoc-$(date +%s) --from=cronjob/hive-rotate
kubectl logs -n hive job/adhoc-<n> -f

# what can actually run right now — the single source of truth
kubectl create job -n hive probe-$(date +%s) --from=cronjob/hive-rotate   # then read the log header
```

After editing any script in `roles/hive_ops/files/bin/`:

```bash
./talos-k8s/hive-ops/deploy.sh      # republishes the ConfigMap and re-applies
```

The scripts are **not** baked into an image. They live in the repo, are
published into `configmap/hive-ops-scripts`, and run on stock `alpine/k8s`.
There is no image to build, push, or keep patched.

## Do not run two control planes

`concurrencyPolicy: Forbid` stops a CronJob racing **itself**. It does nothing
about a systemd timer on a laptop issuing the same mutations at the same time.

`hive-watchdog` and `hive-rotate` are deliberately absent from
`hive_ops_timers` in `roles/hive_ops/defaults/main.yml`. Before re-enabling any
of them, suspend the matching CronJob:

```bash
kubectl patch cronjob -n hive hive-rotate -p '{"spec":{"suspend":true}}'
```

`hive_ops_enabled` is still supported on a host, so the workstation path remains
a working rollback — just never both at once.

## Things that will bite you

**The scripts need `kubectl exec` into the hive pod even from inside the
cluster.** `X-Hive-Internal` authenticates reads but is **read-only** for
mutations; writes need the owner session cookie from
`/data/dashboard-sessions.json` on the hive PVC. Being in-cluster does not
change that — a Go controller would need exactly the same two things.

**Session expiry is decided by the server, not by us.** The session store writes
the hive pod's UTC offset (`-04:00`) while `date -Is` writes the caller's
(`+05:30` on a workstation, `+00:00` in-cluster). Comparing those as strings is
only accidentally correct. The scripts now take the newest owner session and let
a real API call reject it.

**Busybox is not GNU.** The in-cluster image has no `gh`, no `openssl`, and a
`date` with neither `-d "-N day"` nor `-v`. Concretely:
- `hive-metrics.sh` mints a GitHub App installation token and uses `curl`
  instead of `gh` — also the more correct identity than a personal keyring
  token.
- RS256 signing happens **inside the hive pod**, which has `openssl`; only the
  short-lived token crosses back.
- Date arithmetic uses `python3`. An earlier version fell through to an empty
  date, which produced queries like `created:` — those return `0` rather than
  erroring, so the collector published a 14-day series of zeros **over real
  data**.

**The GitHub search API allows 30 requests per minute** for the App token, and a
14-day collection needs 56. `hive-metrics.sh` paces at 9s per day and retries on
the rate limit; a query that still cannot be answered aborts the whole run,
because a partial series published over a good one is worse than no update.

**State is on a `local-path` PVC**, which binds to one node. Every job carries
`nodeSelector: {workload-role: hive}` and the control-plane toleration so it
lands where the hive pod (and therefore the volume) is. Move either and the jobs
sit `Pending` with a volume-node-affinity conflict.

## What the probe means

`probe` is the single indicator of what can run. Everything else — agent
placement, contributor replica counts, whether to strand or resume — is derived
from it:

```
PROVIDER    USED      NOTE
deepseek    100%      balance=-1.23
anthropic    92%      resets=2026-09-02T23:00:00Z
openai      100%      resets 22:35 on 6 Sep
google       37%      resets=2026-09-08T18:54:53Z
```

Two rules worth internalising, both learned the hard way:

- An **unmeasured** provider is allowed as a placement target (otherwise
  evicting its last agent makes it permanently unmeasurable and the fleet
  drains onto one pool), but is **never** treated as recovered.
- A **hard account cap** and a **zeroed credential** are positive exhaustion,
  not failed measurements. Reporting them as "unknown" let rotation fill a
  codex account that was dead for four days, and keep agents on a Claude
  credential whose every pane read `Login expired`.

## What pacing means (and how it differs from the probe)

`probe` answers **can this provider serve** — a threshold, 85–90% depending on
the pool. `hive-pace` answers **should we be going this fast** — a rate. They
are different questions and a threshold cannot answer the second:

- **Overburn.** 22 agents took Anthropic 64% → 69% in ~40 minutes against a cap
  resetting six hours later. The threshold stays silent until 90%, and then the
  fleet parks and sits idle for hours holding quota it spent too early.
- **Underburn.** A cap that resets unused is quota destroyed. The threshold has
  nothing to say about this at all — it is only ever a brake.

```
PROVIDER    VERDICT   PRESSURE  OBSERVED    ALLOWED     DETAIL
anthropic   hot       2.22      12.0 %/hr   5.41 %/hr   69% used, 6.1h left, 2 limit(s), 7 sample(s)
```

**Headroom is not a scalar, and this is the thing to internalise.** Anthropic
returns several *unscoped* limits on independent clocks. Measured 16:55Z:

```
37%  resets 19:30   (5h session)  -> 63 points over 2.6h -> 24.2 %/hr allowed
67%  resets 23:00   (weekly)      -> 33 points over 6.1h ->  5.4 %/hr allowed
100% resets 23:00   scope=Fable   -> model-class cap, EXCLUDED
```

`probe` reports the max, `69% resets 23:00`. Right for availability, useless
for rate — the binding limit is whichever is closest to blowing *its own*
deadline, and the two percentages are on different scales so their rates are
not directly comparable either. Hence `pressure`, a ratio:

    pressure = max over unscoped limits of (observed_rate / allowed_rate)

`>1.25` hot, `<0.75` cold, between is on-pace.

Three behaviours that look like bugs and are not:

- **`learning`** means fewer than 3 samples spanning an hour. It refuses to fit
  a rate on less, because `percent` is an integer and a two-point delta is
  mostly quantization — the "12 %/hr" that motivated this was really somewhere
  in 6–18. After a redeploy it takes ~1h to produce a verdict, and until then
  the fleet runs on `hive-rotate`'s thresholds exactly as before.
- **`pace: 0 change(s)` while hot** is fine *only* if no `SATURATED` line
  follows. That line means the actuator is exhausted — every agent is already
  on the cheap rung — and the remaining levers (cadence, pausing, more capacity)
  are outside this script. That is the line that means intervene.
- **It never promotes an agent it did not demote.** An agent the operator or
  `hive-rotate` placed on the cheap rung stays there; only entries in
  `pace-demoted` are restored when a pool goes cold.

It paces **both hives** (`hive` + `hive-reef`), because one Anthropic
subscription is drained by both. It does *not* control the contributor CLIs,
which draw on the same pools — so it reports how many consumers it actually
owns rather than assuming the fleet is all of them.

It makes **no provider calls of its own**. `hive-rotate` probes once and
publishes the full unscoped limit array to the `hive-provider-usage` ConfigMap
(`anthropic_limits` key); the pacer reads that. A first version polled the
Anthropic usage endpoint itself on a 10-minute cycle and immediately earned
`rate_limit_error`, which degrades the *rotator's* reading too — so the fleet
would have lost its availability signal to gain a pacing signal.

```bash
kubectl logs -n hive -l app.kubernetes.io/component=pace --tail=30
kubectl -n hive get configmap hive-pace -o jsonpath='{.data.pace\.json}' | jq
```

See also: [cluster handbook](cluster.md), [contributor
fleet](../../../../talos-k8s/hive-contributors/README.md),
[console](hive-console.md).
