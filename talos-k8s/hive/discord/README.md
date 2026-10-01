# Hive → Discord reports

These are the TunaOS Discord digests and the #hive-ops feed. They run on the **AWS Talos cluster**, in namespace `hive`:

```bash
export KUBECONFIG=~/.kube/config-aws-migration
```

Until 2026-09-24 this lived only in the cluster. The files here are exported from it and then redesigned. See "What changed" below.

| File | Deployed as |
|---|---|
| `report.py` | ConfigMap `discord-report-code` (key `report.py`) |
| `projects.json` | ConfigMap `discord-report-config` (key `projects.json`), which holds the channel IDs and the repo→channel map |
| `realtime.py` | ConfigMap `discord-realtime-code` (key `realtime.py`) |
| `cronjobs.yaml` | CronJobs `hive-discord-daily-report` (daily 18:00 America/New_York) and `hive-discord-weekly-roundup` (Sun 18:00, currently `suspend: true`) |
| `realtime.yaml` | Deployment `hive-discord-realtime`, Service `hive-discord-realtime-webhook`, PVC `discord-reports-data` (the PVC is for reference only, see below) |

All containers use stock `python:3.12-slim` and mount their code from the ConfigMaps. There are no extra dependencies. `report.py` shells out to `openssl` to sign the GitHub App JWT.

Secrets are never stored here; the manifests only reference them. `discord-report-secrets` holds `DISCORD_BOT_TOKEN` and `GITHUB_WEBHOOK_SECRET`. `hive-secrets` holds `GH_APP_ID`, `GH_APP_INSTALLATION_ID`, `gh-app-key.pem` and `HIVE_DASHBOARD_TOKEN`.

## Data flow

```
GitHub org webhook ──► hive-discord-realtime :8080/api/discord-reports/github
                         ├─ appends /data/github-events.jsonl  (PVC discord-reports-data)
                         └─ (if DISCORD_REALTIME_POSTS=true) urgent notices ──► #hive-ops
Hive dashboard SSE ────► hive-discord-realtime ── login/budget/critical alerts ──► #hive-ops

CronJob report.py ── reads /data/github-events.jsonl (+ Hive /api/status) ──► digest embeds
```

`report.py` falls back to the GitHub API (via the GitHub App) only when the event log does not exist.

## What each message looks like

Every digest is one embed. Its colour is red when something is broken, amber when something needs a decision, and green when nothing needs you. It has these sections, in order, and empty sections are omitted:

1. **Needs you**: newly red build/release workflows, `needs-human` items, held hive PRs, stuck agents, budget, login or breaker problems. When there is nothing, it says **✅ Nothing needs you today.**
2. **Highlights**: up to 5 repos, each described in plain words with the link on the phrase.
3. One italic line that collapses routine work, for example `+17 dependency bumps · +13 hive-agent PRs (…) · +6 nightly/CI builds`.
4. One stats line with deltas against the previous period.

The #hive-ops feed posts only for:
- a build/release workflow on the default branch failing twice in a row, and its recovery
- an agent needing a login, budget exhaustion, or a new critical hive alert
- a real release
- a `needs-human` label, or a new security issue
- the feed itself being down

Everything else is left to the digest. The full rationale is in the audit that went with this change (kept outside the repo).

## Knobs

`report.py` (env):

| Var | Meaning |
|---|---|
| `REPORT_CONFIG`, `REPORT_STATE`, `GITHUB_EVENT_LOG`, `GITHUB_OWNER`, `REPORT_TIMEZONE` | as before |
| `HIVE_DASHBOARD_URL` + `HIVE_DASHBOARD_TOKEN` | optional; adds hive attention items |
| `HIVE_STATUS_FILE` | read a saved `/api/status` JSON instead of calling the dashboard (offline dry runs) |
| `GH_TOKEN` | local runs only: used instead of the GitHub App when `GH_APP_ID` is unset |
| `DRY_RUN=1` / `--dry-run` | print payload JSON and don't post; the state file is never written |
| `--preview` | with `--dry-run`, print a text rendering instead |
| `--now ISO` | re-render a past period |

`realtime.py` (env):

| Var | Default | Meaning |
|---|---|---|
| `DISCORD_REALTIME_POSTS` | `false` | master switch for #hive-ops posting (webhook logging always runs) |
| `REALTIME_BATCH_SECONDS` | 60 | batch window for reds and releases |
| `REALTIME_SLOW_BATCH_SECONDS` | 10800 | batch window for amber/green-only notices |
| `REALTIME_MAX_POSTS_PER_HOUR` | 6 | above this, only reds get through |
| `REALTIME_CI_FAIL_STREAK` | 2 | consecutive failures before a red post |
| `REALTIME_CI_COOLDOWN_SECONDS` | 43200 | don't re-alert a flapping workflow |
| `REALTIME_CI_ALL_WORKFLOWS` | `false` | also alert on lint/prose/etc. workflows |
| `REALTIME_BEAD_POLL` | `false` | poll `/api/beads` and post when a bead becomes *blocked* |
| `DRY_RUN` | unset | print payloads instead of posting |

## Try it locally (no secrets needed)

```bash
cd talos-k8s/hive/discord
# grab a copy of the event log (read-only)
kubectl -n hive exec deploy/hive-discord-realtime -- sh -c 'tail -n 70000 /data/github-events.jsonl | gzip -c' | gunzip > /tmp/events.jsonl
REPORT_CONFIG=projects.json REPORT_STATE=/tmp/state.json GITHUB_EVENT_LOG=/tmp/events.jsonl \
REPORT_TIMEZONE=America/New_York python3 report.py --kind daily --dry-run --preview
```

To run the tests:

```bash
uvx pytest tests/test_discord_report.py tests/test_discord_realtime.py
```

## Deploy

Review first. These commands apply to the live cluster.

```bash
export KUBECONFIG=~/.kube/config-aws-migration
cd talos-k8s/hive/discord

# 1. Code + config (ConfigMaps). Keys must stay report.py / projects.json / realtime.py.
kubectl -n hive create configmap discord-report-code   --from-file=report.py   --dry-run=client -o yaml | kubectl apply -f -
kubectl -n hive create configmap discord-report-config --from-file=projects.json --dry-run=client -o yaml | kubectl apply -f -
kubectl -n hive create configmap discord-realtime-code --from-file=realtime.py --dry-run=client -o yaml | kubectl apply -f -

# 2. Workloads. cronjobs.yaml adds the optional HIVE_DASHBOARD_* env; realtime.yaml adds the REALTIME_* knobs.
kubectl -n hive apply -f cronjobs.yaml
kubectl -n hive apply -f <(yq 'select(.kind != "PersistentVolumeClaim")' realtime.yaml)   # skip the bound PVC

# 3. The Deployment only reads realtime.py at start-up.
kubectl -n hive rollout restart deploy/hive-discord-realtime

# 4. Preview tonight's digest from inside the cluster without posting:
kubectl -n hive create job discord-preview --from=cronjob/hive-discord-daily-report --dry-run=client -o yaml \
  | yq '.spec.template.spec.containers[0].command += ["--dry-run","--preview"]' | kubectl apply -f -
kubectl -n hive logs -f job/discord-preview && kubectl -n hive delete job discord-preview
```

Optional follow-ups:
- `kubectl -n hive patch cronjob hive-discord-weekly-roundup -p '{"spec":{"suspend":false}}'` turns the weekly roundup back on.
- Setting `DISCORD_REALTIME_POSTS=true` on the Deployment turns the quiet #hive-ops feed back on.

The PVC in `realtime.yaml` is for reference only. The live claim is bound to a `local-path` volume, so don't re-apply it. Records written before this version have no `branch`/`trigger` fields, so for older history the CI-streak logic can't tell PR runs from default-branch runs. It becomes accurate as new records accumulate.
