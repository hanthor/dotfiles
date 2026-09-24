# hive-ops — in-cluster operations for the tuna-os Hives

Bash scripts run as CronJobs in namespace `hive` on the AWS Talos cluster
(`KUBECONFIG=~/.kube/config-aws-migration`). They keep the three upstream-v5
Hives working: move agents between providers as quota runs out, pick model rungs by
capability tier, pace spending, pause during DeepSeek peak pricing, and heal
agents that get stuck.

| Hive | Namespace | Rotate state dir |
|---|---|---|
| school (school.tunaos.org, primary) | `hive` | `/state/hive-rotate` |
| reef | `hive-reef` | `/state/hive-rotate-reef` |
| hanthor (hive.reilly.asia) | `hive-hanthor` | `/state/hive-rotate-hanthor` |

- `scripts/`: the contents of ConfigMap `hive-ops-scripts`, mounted at `/scripts`.
  This directory is the source of truth. The older copies in `roles/hive_ops/files/bin/`
  are no longer used (the role is disabled on every host).
- `cronjobs.yaml`: the 21 CronJobs, exported from the cluster with status and managed fields removed.
- Every job runs `alpine/k8s:1.31.0` as ServiceAccount `hive-ops`, with the state
  PVC `hive-ops-state` mounted at `/state`. That PVC is local-path storage on
  `ip-10-20-1-10`, so the jobs have to run on that node.

## Deploy

```bash
export KUBECONFIG=~/.kube/config-aws-migration
cd talos-k8s/hive/ops
# The ConfigMap is too large for client-side apply's last-applied annotation. Use replace:
kubectl -n hive create configmap hive-ops-scripts --from-file=scripts/ \
  --dry-run=client -o yaml | kubectl -n hive replace -f -
kubectl apply -f cronjobs.yaml
```

Then trigger one run and read its log:

```bash
kubectl -n hive create job --from=cronjob/hive-rotate hive-rotate-manual-$(date +%H%M)
kubectl -n hive logs -f job/hive-rotate-manual-...
```

## The jobs

| CronJob | Schedule (UTC) | Script / action | What it changes |
|---|---|---|---|
| `hive-rotate` (+`-reef` :07, `-hanthor` :14) | every 20 min | `hive-rotate.sh apply` | **Backend switching.** Measures quota for every provider. Agents on an exhausted provider move sideways within their capability tier to a provider that has headroom. Unusable backend/model pairs are repaired, a codex canary is placed so openai stays measurable, and contributor Deployments are scaled to 0 or 1 (primary hive only). Pauses declared in `HIVE_ROTATE_HOLD` are kept; other dashboard pauses are resumed. |
| `hive-watchdog` (+`-reef`, `-hanthor`) | every 5 min | `hive-rotate.sh watchdog` | **Liveness.** Classifies each agent's pane: ready, wizard, auth, shell, empty, or **stalled** (turn still open and pane unchanged for 60 min or more). Heals with `POST /api/restart` using exponential backoff (5→120 min). If the backend itself is broken it first rotates the agent off it. Before acting it re-reads the live pane (`GET /api/pane`), because the `/api/status` snapshot can lag by minutes. Also fixes agy `--effort` drift, repairs shared-home permissions, and wakes the fleet when an exhausted provider's reset time passes. At most 3 restart-causing actions per pass. |
| `hive-pace` | :05 :25 :45 | `hive-pace.sh apply` | **Burn-rate pacing.** Fits the burn rate per limit against the time left until reset. When a provider is `hot` it demotes one agent one notch (for example fable/opus → sonnet, gemini-…-high → -low). When `cold` it restores only agents it demoted itself. Covers all 3 hives. |
| `hive-tiers` | 05:50 daily | `hive-tiers.sh refresh` | Rebuilds the **model tier** cache (`tiers.tsv`) from the Artificial Analysis agentic index. rotate merges it with its built-in table. |
| `hive-inventory` | 05:40 daily | `hive-inventory.sh collect` | Lists the models each backend really offers (`inventory.tsv`), so rungs naming unavailable models are dropped. |
| `hive-peak-pause` / `-resume` | 01:00, 06:00 / 04:00, 10:00 Mon–Fri | `hive-peak.sh pause\|resume` | Pauses agents on **DeepSeek** during its weekday peak-price windows, then resumes exactly that set. The set is stored in `/state/hive-rotate/peak-paused`, and rotate treats it as a declared hold. |
| `hive-nudge` | :13 :43 | `hive-nudge.sh nudge` | Kicks agents idle for more than 2× their slowest cadence (at most 4 per hive, 30 s per kick, 420 s per run). Never kicks when the hive's budget is exhausted. |
| `hive-shared-auth` | every 30 min | `hive-shared-auth.sh reconcile` | Checks that `.claude`, `.gemini` and `.codex` really are one store across all hives (write-through test). Repairs group permissions, an unset Claude theme, and a broken agy `statusLine`. |
| `hive-activity` | every 5 min | `hive-activity.sh publish` | Builds the activity feed JSON for hub.tunaos.org (ConfigMap `hive-hub/hub-front`). |
| `hive-metrics` | :23 hourly | `hive-metrics.sh collect` | Publishes a 14-day PR/issue series from GitHub search. Slow by design because of rate-limit pacing, so the deadline is 2400 s. |
| `hive-cli-update` | 05:10 daily | `hive-cli-update.sh update` | Updates the agent CLIs inside the hive pods. |
| `hive-repo-sync` | 03:17 daily | `hive-repo-sync.sh apply` | Syncs the governor repo lists with the GitHub App installation. |
| `hive-fork-*` | suspended | `hive-fork-*.sh` | Legacy v4-fork drift and switch tooling. Suspended since the move to upstream v5. |

Published outputs (ns `hive`):

- `hive-provider-usage`: the latest quota measurement. It includes `anthropic_limits`, `measured_by` and `updated_at`.
- `hive-pace`: pace verdicts.
- `hive-model-inventory`: the model inventory from `hive-inventory`.

## Plan / dry-run

Every script also runs from a workstation. It uses `~/.kube/config-aws-migration` and falls back to `kubectl exec` where it can't reach the hive Service directly.

```bash
cd talos-k8s/hive/ops/scripts
./hive-rotate.sh probe                      # quota per provider (also publishes it)
./hive-rotate.sh plan                       # what apply would do; no changes
HIVE_NS=hive-reef ./hive-rotate.sh plan     # another hive
HIVE_ROTATE_DRYRUN=1 ./hive-rotate.sh watchdog   # classify and report; no heals
HIVE_PACE_DRYRUN=1 ./hive-pace.sh apply     # verdicts; no demotions
./hive-nudge.sh check                       # who is overdue; no kicks
./hive-peak.sh status
./hive-shared-auth.sh check
```

A local run keeps its state under `~/.local/state/`, not in the cluster PVC, so tier and
inventory caches and journals are missing. Plan output can therefore differ from
the CronJob's. For a faithful dry run inside the cluster, start a one-off Job
from the CronJob template with `HIVE_ROTATE_DRYRUN=1` / `HIVE_PACE_DRYRUN=1` added
to `env`.

## How the decisions are made

- **Measurement** (`hive-rotate.sh`, `probe_all`): one `kubectl exec` runs every probe in parallel inside the pod:
  - deepseek: `/user/balance`
  - anthropic: the OAuth usage API
  - openai: `codex app-server` `account/rateLimits/read`
  - google: `agy --print /usage`
  - meta: model catalog only; it has no quota API

  Every hive uses the same accounts, so one measurement is published and reused.
  The primary hive's rotate always measures. The other hives reuse a publication up to 20 min old, and watchdogs up to 30 min old.
  Before this, about 40 hits per hour rate-limited the Anthropic usage API.
- **Rotation** stays put while the current provider is usable and the rung belongs to the agent's tier (it's a failover, not an optimizer). Otherwise it chooses:
  1. the cheapest provider class first: agy (free) → claude → codex → deepseek (metered);
  2. peak-priced providers last within that class;
  3. the least-used provider after that.

  A rung the pacer demoted the agent to also counts as in-tier. Before that rule, rotate and pace undid each other every tick.
- **Tiers** combine the built-in `TIERS` table in `hive-rotate.sh` with `tiers.tsv`, filtered by `inventory.tsv`. Only `-contributor` models are allowed for muse.
- **agy effort (v5)**: v5 starts agy with `--effort <agent effort>`, which defaults to `low`. agy ignores a `-high` or `-medium` model id when the effort doesn't match and runs Gemini 3.6 Flash (Low) instead. Every agy placement therefore also calls `POST /api/effort/{agent}/{effort}`.

## Plumbing notes (why the scripts look the way they do)

See the header of `scripts/hive-lib.sh`. In short:

- v5 `/api/status` is about 3 MB. It's fetched once per run over the hive Service and reduced to the fields the scripts use.
- The hive node runs at a load of ~85 on 4 vCPUs. Under that load kubectl takes 8 s just to start, and 10–35 s per call.
  The scripts therefore reach the Kubernetes API with curl and the ServiceAccount token, and cache the owner session cookie (a rejected cookie is re-read).
  `kubectl exec` is used only where nothing else works.
- `KUBECTL_REMOTE_COMMAND_WEBSOCKETS=false`: the `hive-ops` Role grants `create` on
  `pods/exec` but not `get`, so kubectl's WebSocket attempt always fails with 403 before falling back to SPDY.
- Mutations (`/api/switch|model|effort|restart`) restart the agent while the request is open, so the client timeout is 150 s.

Tests: `uvx --with pyyaml pytest -q tests/test_hive_ops_lib.py`, and `shellcheck -S warning -x scripts/*.sh`.
