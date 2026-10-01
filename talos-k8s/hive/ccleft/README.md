# ccleft — remaining quota for the Hives' agent accounts

[ccleft](https://github.com/tuna-os/ccleft) asks each provider how much quota
is **left** on the accounts the Hive agents use (Claude, Codex, agy/Antigravity,
Kiro, DeepSeek, …) and when it resets. It serves the answers on
`http://ccleft.hive.svc:9464`:

| path | what |
|---|---|
| `GET /readings` | JSON, one reading per `(provider, account)`: state, windows (used/limit/remaining/%/resets_at), stale flag, homes. `?provider=claude` filters. |
| `GET /metrics` | Prometheus text: `ccleft_remaining_ratio`, `ccleft_remaining`, `ccleft_reset_timestamp_seconds`, `ccleft_state`, `ccleft_stale`, … and `ccleft_upstream_requests_total{provider,state,cause}` (calls ccleft made to the quota endpoints). |
| `GET /healthz` | 200 once the first refresh has completed. |

The operator (`tuna-os/hive-operator` `UsagePool.spec.ccleft`) reads
`/readings`, and so do `hive-rotate` / `hive-pace` (see "The bash probes read
ccleft" below).

## Files

- `config.yaml`: ConfigMap `ccleft-config`, listing the homes to probe and each provider's minimum interval between upstream calls.
- `deployment.yaml`: ServiceAccount `ccleft` (no token, no RBAC), Deployment `ccleft` and Service `ccleft`.

```bash
export KUBECONFIG=~/.kube/config-aws-migration
kubectl apply -f talos-k8s/hive/ccleft/config.yaml -f talos-k8s/hive/ccleft/deployment.yaml
kubectl -n hive logs deploy/ccleft            # one "upstream" line per quota call
kubectl -n hive exec deploy/ccleft -- curl -s localhost:9464/readings | jq '.readings[] | {provider, state, stale, w: [.windows[] | {id, remaining_pct, resets_at}]}'
```

Applying these creates or updates only the four objects above. It does not
touch any hive Deployment or pod, the hive-ops CronJobs or their ConfigMap, or
any PVC.

## Design

**One pod, in namespace `hive`, for all three Hives.** A PVC can only be
mounted in its own namespace. Normally that would mean one ccleft per Hive
namespace, each polling the same accounts, which is three times the calls to
Anthropic's already rate-limited usage endpoint. Here it doesn't need to:

- `.claude`, `.codex` and `.gemini` for `hive`, `hive-reef` and `hive-hanthor`
  are the **same host directory**. Every `shared-*` PV is a hostPath onto the
  `hive/hive-shared-auth` volume. The per-agent homes symlink their dot-dirs
  to `/data/home`, and every `.codex-<agent>/auth.json` is a symlink to
  `/data/home/.codex/auth.json`.
- `KIRO_API_KEY`, `DEEPSEEK_API_KEY` and `META_API_KEY` hash identically in all
  three namespaces (checked 2026-09-25, as `hive-rotate.sh` notes).
- Copilot is logged in nowhere (the copilot CLI log says "Logged out", and
  there is no `github-copilot/apps.json`).

So mounting the primary Hive's `hive-data` plus `shared-{claude,gemini,codex}`
in `hive` covers every account every Hive uses. ccleft dedupes the 57 detected
sources (shared home plus 13 agent homes × providers) down to 7 readings, one
per account. That means one upstream call per account per interval, whichever
Hive is asking. If a spoke ever gets a login of its own, run a second copy of
these manifests in that namespace. The operator keys readings by
`(provider, account)`, so the two instances will not double count.

**The binary comes from an image volume.** agy has no HTTP quota API, so
ccleft has to run the `agy` CLI. The container is therefore the Hive's own
image (`ghcr.io/hivecommons/hive`, same digest as `deploy/hive`), and ccleft is
mounted from `ghcr.io/tuna-os/ccleft` (published by the ccleft repo's
`publish` workflow, pinned by digest) as a Kubernetes **image volume**: read-only
and executable, with no initContainer or copy step. This needs k8s ≥ 1.33 and
containerd ≥ 2.1; this cluster runs 1.36 and 2.2.

**Read-only by construction.**
- Every agent-home mount is `readOnly` (the kernel enforces `ro`).
- The pod runs as `1001:1000` (`dev:node`, the owner and group of the home
  files, which are mode `0660`) with no `fsGroup`, so kubelet chowns nothing.
- `readOnlyRootFilesystem`, all capabilities dropped, no privilege escalation.
- No service-account token.
- ccleft never refreshes tokens and never runs `claude` or `codex`.
- agy 1.2.10 answers `/usage` with a read-only `HOME`: it logs that it cannot
  write its log file and carries on.
- Checked at deploy time, 2026-09-25: every credential file's mtime was
  unchanged across ccleft's first probe cycle. Over the following hour the
  only changes were the Hive's own refreshes: Claude Code rotating
  `.credentials.json` 5 s before `expiresAt`, and agy's hourly token
  rotation. Neither coincided with a ccleft probe, and ccleft's mounts are
  `ro` anyway.

**Secrets:** only env vars the hive pod already has:
- `KIRO_API_KEY` (Secret `kiro-api`).
- `DEEPSEEK_API_KEY` (Secret `hive-secrets`, optional). The balance is exhausted and unfunded.
- `META_API_KEY` (Secret `hive-secrets`, optional). It is only used to report muse as `unsupported`; it makes no network call.

The OAuth tokens are read from the mounted homes and sent only to their own
provider.

**Rate limits** (`min_interval` in `config.yaml`): claude 10 m, codex/agy/kiro
5 m, deepseek 30 m. That is at most one upstream call per account per
interval, whatever the refresh period and however many homes share the
account. On a 429 or network error, ccleft serves the last good reading marked
`stale: true`, and backs off (at least the min interval, doubling to 30 m, and
honouring `Retry-After`).

## Scraping

**No Prometheus runs on this cluster** (no `monitoring.coreos.com` CRDs, no
Prometheus pods, as of 2026-09-25), so no ServiceMonitor is shipped. The
Service carries the conventional `prometheus.io/scrape|port|path` annotations,
so an annotation-based scraper picks it up if one is added. Useful queries:

```promql
min by (provider, account) (ccleft_remaining_ratio{binding="true"})     # headroom
sum by (provider) (increase(ccleft_upstream_requests_total[1h]))        # our load on each quota API
ccleft_upstream_requests_total{state="rate_limited"}                   # throttling
```

## Maintenance

- **Hive image upgrade:** bump the `image:` digest here to match `deploy/hive`, so that ccleft's `agy` matches the agents' `agy`.
- **ccleft upgrade:** take the digest from the ccleft repo's `publish` run summary, or `sha-<commit>` on GHCR, and update `volumes[ccleft-bin].image.reference`.
- **Agents added or removed:** edit the `homes:` list in `config.yaml`. A missing agent home is harmless (the entry detects nothing); a new one is only needed to prove dedupe or to catch a per-agent login.
- **Keep one replica** (`Recreate`). Two pods would double the upstream calls.

## The bash probes read ccleft (2026-09-25)

`hive-rotate` (every rotate and watchdog run, all three hives) and `hive-pace`
now read `/readings` instead of polling the providers themselves
(`HIVE_PROBE_SOURCE=ccleft` on their CronJobs; see
[`../ops/README.md`](../ops/README.md), "How the decisions are made"). ccleft is
therefore the only caller of Anthropic's usage endpoint. The old direct probes
remain as a fallback for a run in which ccleft cannot be reached, and it logs
`FALLING BACK TO DIRECT PROVIDER PROBES`. Still to do: the operator's UsagePools
read ccleft, and `probe_all` can be removed once the fallback has gone unused for a while.

Before the switch, busybox `date` in the ops image could not parse the
publication timestamp, so every rotate and every watchdog (3 hives × every
5 min) polled Anthropic directly. ccleft's claude calls came back 429 about 5
times in 6.
