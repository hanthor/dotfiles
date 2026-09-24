# hive-ops — in-cluster operations for the tuna-os Hives

Bash scripts run as CronJobs in namespace `hive` on the AWS Talos cluster
(`KUBECONFIG=~/.kube/config-aws-migration`). They keep the three upstream-v5
Hives working: move agents between providers as quota runs out, pick model rungs by
capability tier, pace spending, keep the Kiro provider for `pi` installed, and heal
agents that get stuck.

| Hive | Namespace | Rotate state dir |
|---|---|---|
| school (school.tunaos.org, primary) | `hive` | `/state/hive-rotate` |
| reef | `hive-reef` | `/state/hive-rotate-reef` |
| hanthor (hive.reilly.asia) | `hive-hanthor` | `/state/hive-rotate-hanthor` |

- `scripts/`: the contents of ConfigMap `hive-ops-scripts`, mounted at `/scripts`.
  This directory is the source of truth. The older copies in `roles/hive_ops/files/bin/`
  are no longer used (the role is disabled on every host).
- `cronjobs.yaml`: the 22 CronJobs, exported from the cluster with status and managed fields removed.
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
| `hive-peak-pause` / `-resume` | suspended | `hive-peak.sh pause\|resume` | Paused agents on **DeepSeek** during its weekday peak-price windows. Suspended 2026-09-24: DeepSeek is no longer used and nothing else is peak-priced. |
| `hive-pi-kiro` | :37 hourly | `hive-pi-kiro.sh reconcile` | Keeps the pinned, patched pi-kiro-api checkout at `/data/pi-packages/pi-kiro-api` on each hive PVC and registers it in every agent's `~/.pi/agent/settings.json`. See [Kiro](#kiro-pi--pi-kiro-api). |
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
  - kiro: `GetUsageLimits` (credits used / monthly limit, reset date, overage status)
  - anthropic: the OAuth usage API
  - openai: `codex app-server` `account/rateLimits/read`
  - google: `agy --print /usage`
  - meta: model catalog only; it has no quota API

  Every hive uses the same accounts, so one measurement is published and reused.
  The primary hive's rotate always measures. The other hives reuse a publication up to 20 min old, and watchdogs up to 30 min old.
  Before this, about 40 hits per hour rate-limited the Anthropic usage API.
- **Rotation** stays put while the current provider is usable and the rung belongs to the agent's tier (it's a failover, not an optimizer). Otherwise it chooses:
  1. the cheapest provider class first: agy (free) → kiro (Kiro Power credits) → claude → codex;
  2. peak-priced providers last within that class;
  3. the least-used provider after that.

  A rung the pacer demoted the agent to also counts as in-tier. Before that rule, rotate and pace undid each other every tick.
- **Tiers** combine the built-in `TIERS` table in `hive-rotate.sh` with `tiers.tsv`, filtered by `inventory.tsv`. Only `-contributor` models are allowed for muse.
- **agy effort (v5)**: v5 starts agy with `--effort <agent effort>`, which defaults to `low`. agy ignores a `-high` or `-medium` model id when the effort doesn't match and runs Gemini 3.6 Flash (Low) instead. Every agy placement therefore sends the matching `reasoning_effort` in the same atomic `PUT /api/config/agent/{name}/models` (hivecommons/hive#8714).

## Plumbing notes (why the scripts look the way they do)

See the header of `scripts/hive-lib.sh`. In short:

- v5 `/api/status` is about 3 MB. It's fetched once per run over the hive Service and reduced to the fields the scripts use.
- The hive node runs at a load of ~85 on 4 vCPUs. Under that load kubectl takes 8 s just to start, and 10–35 s per call.
  The scripts therefore reach the Kubernetes API with curl and the ServiceAccount token, and cache the owner session cookie (a rejected cookie is re-read).
  `kubectl exec` is used only where nothing else works.
- `KUBECTL_REMOTE_COMMAND_WEBSOCKETS=false`: the `hive-ops` Role grants `create` on
  `pods/exec` but not `get`, so kubectl's WebSocket attempt always fails with 403 before falling back to SPDY.
- Mutations restart the agent while the request is open, so the client timeout is 150 s.
- **Placement is one atomic call**: `PUT /api/config/agent/{name}/models` with
  `{"backend","model"}`, plus `"reasoning_effort"` for agy. `hive_placement_body`
  builds the body and `hive_placement_ok` checks the answer. v5.35 applies it to
  the live launch config and restarts once (hivecommons/hive#7374). This was
  re-verified on `hive` on 2026-09-24. The old `/api/switch` + `/api/model` pair
  restarted twice and could leave an unlaunchable pair (#8714/#8723).
  `/api/effort` is still used for an effort-only drift fix.

Tests: `uvx --with pyyaml pytest -q tests/test_hive_ops_lib.py`, and `shellcheck -S warning -x scripts/*.sh`.

## Kiro (pi + pi-kiro-api)

The owner's **Kiro Power** subscription replaced DeepSeek on 2026-09-24. v5 has no
kiro backend, so Kiro runs through the **`pi`** backend with the pi package
[pi-kiro-api](https://github.com/satiyap/pi-kiro-api), which registers provider
`kiro-api-key`. Agents are placed with backend `pi` and model
`kiro-api-key/<model>:<thinking>` (for example
`kiro-api-key/claude-sonnet-5:medium`). v5 starts them as
`pi --model <that>`. **The `:<thinking>` suffix is required.** v5's
`normalizeModelNameForBackend` rewrites a trailing `-<digits>` to `.<digits>`
for every backend except claude and bob. Without the suffix,
`kiro-api-key/claude-opus-5` launched as `claude-opus.5`, an id pi does not know.
The ladder uses these rungs:

| Tier | Rungs |
|---|---|
| T1 | `claude-opus-5:high`, `gpt-5-6-sol:high` |
| T2 | `claude-sonnet-5:medium`, `gpt-5-6-luna:medium` |
| T3 | `claude-haiku-4-5:low` |

Place agents with the API as usual. The model path segment is URL-escaped
(`hive_model_path`), because `/` inside `{model}` would otherwise 404.

**Key.** Bitwarden secure note `kiro-api-key`. It goes into Secret `kiro-api`
(key `KIRO_API_KEY`) in each hive namespace. From there it becomes an env entry on
container `hive` (`secretKeyRef`, optional), and the tmux server passes it on to
every agent. Run `talos-k8s/hive/kiro/wire-kiro-key.sh <ns>`. It is idempotent.
Adding the env restarts the pod (Recreate), so do one hive at a time, and leave
~10 min between `hive` and `hive-reef`, which share one GitHub App. hive-upgrade's
strategic-merge patch only sets `image`, so it keeps the env.

**Package persistence.** `pi install npm:…` writes to the image's global npm
prefix, which is lost on every pod restart. Instead, `hive-pi-kiro.sh` does two things:

- It keeps a git checkout on the hive PVC at `/data/pi-packages/pi-kiro-api`. The
  checkout is pinned to fork commit `hanthor/pi-kiro-api@1c06115`
  (`fix-apikey-env-reference`, upstream PR satiyap/pi-kiro-api#1) plus
  `scripts/pi-kiro-api-pi087.patch`.
- It registers that path as a local package in each agent's own
  `~/.pi/agent/settings.json` (per-agent HOME `/data/home/agents/<agent>`, also on
  the PVC).

The `hive-pi-kiro` CronJob re-runs this hourly for new agents. The patch is needed
with the image's pi 0.87.1:

- pi 0.8x moved the system prompt and tools into `role:"system"` messages. The
  extension turned them into a `toolResult` with no `toolUseId`, and Kiro answered
  400 `Invalid tool use format.`
- pi 0.87 resolves `"$VAR"` templates in a provider `apiKey` and sends a bare name
  literally, the opposite of 0.73. The stream now reads `KIRO_API_KEY` from the env.

*Switching back to upstream:* once a release carries both fixes, set
`HIVE_PI_KIRO_REPO`/`HIVE_PI_KIRO_SHA` to it and `HIVE_PI_KIRO_PATCH=""` in the
CronJob, then run it once.

**Quota.** `AmazonCodeWhispererService.GetUsageLimits` (same endpoint and key)
returns what rotate and pace need:

- 10000 **credits** per calendar month;
- reset on the 1st at 00:00Z;
- `overageStatus: DISABLED`, so 100% is a hard stop. Rotate's threshold is 95%.

Credits per request scale with the model's `rateMultiplier` from `ListAvailableModels`:

| Model | Credits per request |
|---|---|
| opus-5 | 2.2 |
| sonnet-5 | 1.3 |
| haiku-4.5 | 0.4 |
| gpt-5.6 sol | 4.4 |
| gpt-5.6 terra | 2.2 |
| gpt-5.6 luna | 1.1 |

**Measured burn (2026-09-24).** 16 agents on Kiro burned ~470 credits/hour against
a pace allowance of ~65/hour. pi re-sends the whole context on every step, and one
pass read 0.5–6 M input tokens. So rotate never places an agent kicked more often
than every 15 min (`HIVE_ROTATE_KIRO_MIN_CADENCE_S`, default 900) on Kiro, and
moves such an agent off it. Rotate publishes the reading as
`kiro: N% used credits=U/L resets=…`. Pace fits the exact
credit count, because 1% is 100 credits. The pace rungs are
`opus-5 → sonnet-5` and `gpt-5.6 sol/terra → luna`.

Test pi as an agent inside a pod:

```bash
kubectl -n hive-hanthor exec deploy/hive -c hive -- su-exec hive-architect \
  env HOME=/data/home/agents/architect HTTPS_PROXY=http://127.0.0.1:18443 \
  NODE_EXTRA_CA_CERTS=/data/proxy-ca.pem pi --model kiro-api-key/claude-sonnet-5 \
  --no-session --mode json -p 'Use bash to run: echo ok' | jq -c 'select(.type=="message_end")'
```

## Muse (meta) caveat

v5.35 has no muse case in its hosted launcher, so agents run bare `muse`. That
means `--approval-mode on-request` and the LLM approval judge. The
`--approval-mode never` in backends.conf applies only to the contributor path.
The judge sometimes escalates a command to a human prompt ("Would you like to run
the following command? … Yes, proceed (y)"), typically one that reads the env.
On 2026-09-24, 2 of 4 muse agents parked there for 38–53 min. The watchdog
classifies that pane as `approval` and rotates the agent off muse, as it does for
`auth`. Restarting would only ask again. Muse stays a last-resort T2/T3 rung until
upstream launches it unattended.

