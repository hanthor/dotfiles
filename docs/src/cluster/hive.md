# Hive — AI Agent Supervisor

## Current deployment: Spindle VPS

The school and reef Hives and their hub are deployed on the
[Spindle VPS](../servers/spindle-vps/README.md), not Kubernetes. On 2026-10-27,
read-only inspection found the `school`,
`reef`, `hub`, and `hub-front` Docker Compose services running under
`/srv/hives` on `spindle` (`ubuntu@100.113.75.88` over Tailscale). The live
Caddy configuration routes [school.tunaos.org](https://school.tunaos.org) and
[reef.tunaos.org](https://reef.tunaos.org) to their spokes, and
[hub.tunaos.org](https://hub.tunaos.org) to the hub and its frontend. Container
state alone does not establish that the public endpoints or agents are healthy.

The configured images are `ghcr.io/hivecommons/hive:v6-latest` for the two
spokes and `ghcr.io/hivecommons/hive-hub:v6-latest` for the hub, but the image
tag does not describe the running binary. `compose.override.yaml` bind-mounts a
`tuna-os/hive` fork build over `/usr/local/bin/hive` on all three services and
mounts a patched `proxy/server.js` on both spokes. The header comment in that
file records which commit each `bin/hive-<sha>` contains. The fork's
`tuna/v6` branch is upstream `v6` plus the patches the fleet pilots; the
tracker is [tuna-os/tunaOS#4072](https://github.com/tuna-os/tunaOS/issues/4072).
Since 2026-10-30 the agents use the `omp` backend with
`openai-codex/gpt-6-luna` through the `omp-auth-broker` user service, and the
ioscan classifier runs through omp on `anthropic/claude-haiku-4-5`.
Reef and School's Matrix pilot uses commit-pinned builds from
`deploy/upstream-v6-matrix`, rather than a moving image tag; Hub stays on
`230f745`. Canary and fleet pins can differ during a rollout.
See [the fleet ledger](https://github.com/tuna-os/hive/blob/docs/spindle-matrix-rollout/FORK.md#what-the-fleet-runs)
for the per-service rollout state and
[integration PR #172](https://github.com/tuna-os/hive/pull/172) for CI and provenance.

### Layout under `/srv/hives`

| Path | Contents |
|---|---|
| `compose.yaml`, `compose.override.yaml` | Services; the override pins the fork binary, proxy patch and matching Matrix dashboard HTML |
| `.env` (mode 600) | `HIVE_HUB_SECRET`, `HIVE_DASHBOARD_TOKEN`, `OMP_AUTH_BROKER_TOKEN`, `NTFY_TOPIC` and provider API keys. Copy in Bitwarden: `hive-spindle-env` |
| `<svc>/config/hive.yaml` | Seed config, mounted read-only at `/etc/hive` |
| `<svc>/data/` | `/data`. `hive.yaml.runtime` is the running config and **wins over the seed** for `github.*` and most other keys, so change both |
| `<svc>/secrets/gh-app-key.pem` | GitHub App private key, mounted at `/secrets` |
| `bin/` | Fork builds, `hive-<sha>`, and matching `dashboard-<sha>.html`; earlier builds stay for rollback |
| `backups/` | Timestamped copies taken before each change: `<file>.<UTC stamp>` |

### GitHub Apps

Since 2026-10-30 School and Reef use separate GitHub Apps, so each has its own
installation rate limit (6,150 requests/hour across the 43 org repos). Before
that they shared one installation and exhausted it every hour.

| Hive | App (bot login) | App ID | Installation | Key in Bitwarden |
|---|---|---|---|---|
| school (the hub mounts the same key) | `hanthor-hive-agent` (`hanthor-hive-agent[bot]`) | 3942065 | 137498420 | `hive-github-app-hanthor-hive-agent` |
| reef | `tuna-reef-hive` (`tuna-reef-hive[bot]`) | 5546574 | 177007234 | `hive-github-app-tuna-reef-hive` |

The IDs appear in three places per hive: `GH_APP_ID`/`GH_APP_INSTALLATION_ID`
in `compose.yaml`, and `github.app_id`/`installation_id` in both the seed and
`hive.yaml.runtime`.

Both hives manage `.github`, `Tavern`, `bluefin-cli`, `corral`, `docs` and
`flatpak-index`. Each therefore lists the other's bot in
`github.additional_bot_logins`, so the other hive's issues and PRs count as
hive-authored.

To restore a key, write the Bitwarden note's key block to
`<svc>/secrets/gh-app-key.pem` (`ubuntu:ubuntu`, mode 600), then recreate the
service with `docker compose up -d <svc>`.

To check that each hive is on its own budget, run:

```bash
ssh ubuntu@100.113.75.88 'for c in hives-school-1 hives-reef-1; do docker exec $c sh -c \
  "curl -s -H \"Authorization: Bearer \$(cat /var/run/hive-metrics/gh-app-token.cache)\" https://api.github.com/rate_limit" \
  | jq -c .resources.core; done'
```

Different `reset` times mean separate installations.

The old AWS cluster also had a `hive.reilly.asia` spoke; no hanthor container
was present in the inspected Spindle Docker inventory. Its current status was
not established. The former [hive_ops role](../roles/hive_ops.md) targets the
retired cluster, not this Compose deployment.

For a read-only inventory, run:

```bash
ssh ubuntu@100.113.75.88 'docker ps --filter name=hives-'
```

### Ambient code-rain pilot

The pilot ports upstream's Matrix observer, privacy fixes, JSON/SSE API and
four effects (Rain, Cascade, Ghost coder, Terminal) onto v6 while retaining
the fork's SDLC policies. It is a dashboard feature, not a Twitch deployment.

After signing in to the corresponding dashboard, open:

- [Reef kiosk](https://reef.tunaos.org/?kiosk=1&view=matrix&sound=off&mx.effect=rain)
- [School kiosk](https://school.tunaos.org/?kiosk=1&view=matrix&sound=off&mx.effect=rain)

Use `mx.effect=cascade`, `ghost` or `terminal` to change the effect, and
`mx.fps=15` to lower rendering load. Space/P pauses; sound is explicitly off.
Each spoke shows admitted patches from its watched repositories, not all
hub repositories. Known peer bots can appear where watches overlap.
This is not a hub-wide aggregated code feed or a keystroke stream.

`dashboard.matrix` must be enabled in **both** seed and runtime configs.
`repos` is an explicit allowlist of already-watched, verified-public repos.
The pilot excludes `deploy/**`, `config/**`, `.github/**`, YAML, JSON and TOML
in addition to upstream's built-in secret filtering. Do not add private
repos: the feed has no per-repository viewer permissions.

An anonymous `/api/matrix/lines?since=0` must return 401/403.
An authenticated response reports `source: "pushed-lines"` and sequence
numbers. Animation can replay buffered patches and is not proof of a new
push. The source is initialized by the sentinel sweep after reconciliation;
a cold start can return 404 even with the flag enabled until that sweep runs.
Do not disable budget, admission or writeback guards to accelerate the feed.

Before `637bae44f`, short `project.repos` names (with `project.org` set) were
passed unchanged to Matrix's qualified `owner/name` allowlist, silently dropping
every patch. The fix qualifies observation names; it does not relax admission.
An active API with `seq: 0` therefore did not prove that these hives were idle.
See the fleet ledger for deployment and live verification of that fix.

Before an upgrade, stop the affected service, snapshot its retained data,
copy both configs and the Compose override into `backups/`, then start it
with a commit-matched binary and HTML. The 2026-10-31 Reef canary backup stamp
is `20261031T180544Z`; School's is `20261031T182146Z`.
Both previous binaries are `bin/hive-230f745`.
For rollback, stop the service, restore its matching binary/UI pins and both
config files, validate Compose, and restart. Restore the data snapshot only
when required for downgrade compatibility; do not overwrite newer agent work
as a routine rollback step.

## Archived cluster guide

> **Historical reference only — do not apply or run the Kubernetes, image-build,
> secret, restart, or state-reset instructions below.** The AWS Talos cluster
> was terminated on 2026-10-25; its Kubernetes resources and CronJobs are not a
> current deployment. The home Talos cluster (bihar and karnataka) is powered
> down temporarily, not decommissioned. Preserve its configurations. The
> sections below describe older home-cluster and AWS configurations at different
> points in time, not the current Spindle service. See the
> [AWS cluster history](../servers/aws-k8s/cluster.md) and
> [historical cluster manifests](https://github.com/hanthor/dotfiles/tree/master/talos-k8s/hive).
> Examples are retained for context, not as instructions for either cluster.

The earlier home-cluster Hive used pi with DeepSeek, tmux agents, a governor,
and a GitHub App. The architecture and examples below are snapshots of that
period; later AWS configurations and the current Compose deployment differ.
---

## 1. Architecture (historical)

```
┌──────────────────────────────────────────────────────────────┐
│ Namespace: hive (node: bihar)                                │
│                                                              │
│  ┌─────────┐  ┌──────────┐  ┌────────────────────────────┐  │
│  │ hive    │  │ proxy    │  │ 9x pi agents (tmux sessions)│  │
│  │ Go bin  │  │ node.js  │  │                            │  │
│  │ :3002   │  │ :3001    │  │ supervisor  ADVISORY       │  │
│  │ (API)   │  │ (web UI) │  │ scanner     ISSUES_AND_PRS │  │
│  └────┬────┘  └────┬─────┘  │ ci-maintain ISSUES_AND_PRS │  │
│       │            │        │ quality     ISSUES_AND_PRS │  │
│       └────────────┘        │ sec-check   ISSUES_AND_PRS │  │
│                             │ guide       ISSUES_AND_PRS │  │
│  ┌──────────────────────────│ architect   ISSUES_AND_PRS │  │
│  │  pi → DeepSeek API       │ strategist  ISSUES_AND_PRS │  │
│  │  (native, no proxy)      │ brainstorm  on-demand     │  │
│  │  GitHub App → gh CLI     └────────────┬───────────────┘  │
│  └───────────────────────────────────────┘                  │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ ConfigMap│  │ Secret   │  │ PVC      │                  │
│  │ hive.yaml│  │ DEEPSEEK │  │ hive-data│                  │
│  │ backends │  │ GH App   │  │ (10Gi)   │                  │
│  └──────────┘  └──────────┘  └──────────┘                  │
└──────────────────────────────────────────────────────────────┘
         │
    ┌────▼────┐     ┌──────────────────┐
    │ GitHub  │     │ Tailscale Ingress │
    │ tuna-os │     │ hive.manatee-     │
    │ repos   │     │ basking.ts.net    │
    └─────────┘     └──────────────────┘
```

### Components

| Component | Language | Purpose |
|-----------|----------|---------|
| **hive** (Go binary) | Go | Agent manager, governor, scheduler, dashboard API |
| **proxy** (Node.js) | JS | Dashboard web UI + SSE, proxies to Go API |
| **pi** (coding agent) | Node.js | AI agent CLI running in tmux sessions |
| **pi-wrapper.sh** | Shell | Tmux interface adapter — restart loop, ready markers |

### How agents work

Each agent runs as a long-lived **pi** process inside a tmux session. The Go binary:

1. Creates a tmux session per agent (`hive-supervisor`, `hive-scanner`, etc.)
2. Writes a boot prompt (agent role, authorized repos, instructions) via `send-keys`
3. Detects agent readiness from CLI markers in the pane output
4. **Governor** evaluates the issue queue every 5 minutes and sends *kick* prompts to due agents
5. `clear_on_kick: true` agents receive `^C` before each kick to reset their session

Agents share a persistent `/data` volume (10Gi PVC) for beads, session state, and agent configs.

---

## 2. What Hive did (historical)

### Advisory digest

The dashboard shows agent findings — CI failures, test coverage gaps, security issues, documentation problems. Each agent produces **beads** (structured findings) that appear in the advisory digest.

### Issue creation

At ACMM L3+, agents create GitHub issues. At L4+, they can create hold-gated PRs. The **sec-check** agent scans dependencies for CVEs. The **ci-maintainer** agent monitors CI failures.

### Strategy Lab

Inception feature: describe what you want to build, and Hive scaffolds a new project with knowledge base facts and spec-kit specifications. Powered by the **brainstorm** agent (on-demand).

### Knowledge Base

Agents can contribute facts to a shared knowledge base. Facts are tagged by type (pattern, gotcha, regression, decision, etc.) and searchable from the dashboard.

---

## 3. Deployment (historical)

### Namespace and resources

The home-cluster deployment used the `hive` namespace on bihar:

```
hive (namespace)
├── deploy/hive           — main controller pod
├── svc/hive              — ClusterIP :3001 (dashboard), :3002 (API), :7681 (ttyd)
├── ingress/hive          — Tailscale ingress → hive.manatee-basking.ts.net
├── configmap/hive-config — hive.yaml (project config, agents, governor)
├── secret/hive-secrets   — DEEPSEEK_API_KEY, GH App credentials
├── pvc/hive-data         — 10Gi persistent state
└── secret/ghcr-auth      — GHCR pull credentials
```

### Historical files (not the current repository layout)

```
talos-k8s/hive/
├── hive.yaml              — All K8s resources (namespace, deploy, svc, ingress, configmap)
├── Dockerfile             — Custom image (hive v2 + pi + fd/ripgrep)
├── pi-wrapper.sh          — Wrapper: Hive tmux interface → pi interactive TUI
├── pi-marker.patch        — Adds "pi" to hive's cliPaneMarkers (source patch)
├── build-job.yaml         — Kaniko build job (deprecated, use CI)
├── deepseek-chat.py       — Python fallback (unused with pi)
├── goose-wrapper.sh       — Legacy goose wrapper (replaced by pi-wrapper.sh)
├── goose-marker.patch     — Legacy goose patch (replaced by pi-marker.patch)
├── SKILL.md               — Skill file for pi coding agent
├── README.md              — Quick reference
└── HANDOFF.md             — Debugging session notes
```

### CI workflow

The former `.github/workflows/hive-build.yml` workflow did the following:

1. Clones `kubestellar/hive` v2 source
2. Applies `pi-marker.patch` and three sed patches to the Go source:
   - Adds `"pi"` to `cliPaneMarkers` (so agents aren't detected as crashed)
   - Adds `"pi": true` to `validBackends` (config validation)
   - Adds `"pi": "pi"` to `backendBinary()` (binary resolution)
3. Cross-compiles Go binary for amd64
4. Builds Docker image with pi + pi-wrapper.sh + fd/ripgrep
5. Pushes to `ghcr.io/hanthor/hive:latest`

### Secrets and deployment (historical)

The home-cluster pod used a Kubernetes Secret for DeepSeek and GitHub App
credentials. Later, the AWS deployment exported spoke manifests under
`talos-k8s/hive/spokes/` and used the hive-operator to manage images. These
manifests are historical records, **not deployment instructions**. The home
cluster's former Tailscale ingress was `hive.manatee-basking.ts.net`.

---

## 4. AI backend: pi + DeepSeek (historical)

### Why pi (not goose)

Hive originally used **goose** (v1.36 from AAIF) as the AI agent CLI. Goose does not natively support DeepSeek, requiring a **Python proxy** (`deepseek-proxy.py`) to:

- Strip `reasoning_content` from message history
- Inject `thinking:{type:disabled}` to prevent thinking block generation
- Route through `litellm` pointing at a local proxy

This was fragile. **pi** natively supports DeepSeek via its `deepseek` provider — no proxy, no litellm, no workaround.

### Why pi works for unattended agents

Pi intentionally has **no permission popups** — tools (`read`, `write`, `edit`, `bash`) auto-execute without user confirmation. This makes it ideal for Hive's unattended agent workflow where no human is available to approve tool calls.

### pi-wrapper.sh

The wrapper translates Hive's backend CLI interface to pi:

```bash
# Hive calls: pi --no-confirm --model deepseek-v4-pro
# Wrapper strips --no-confirm (pi doesn't need it), passes --model to pi
# Sets up ~/.pi/agent/settings.json with DeepSeek config
# Runs pi in interactive TUI mode inside the tmux pane
# Restart loop: ^C from clear_on_kick kills pi-real, wrapper re-emits ready markers
```

### pi configuration

Written at runtime by the wrapper:

```json
{
  "defaultProvider": "deepseek",
  "defaultModel": "deepseek-v4-pro",
  "quietStartup": true,
  "hideThinkingBlock": true,
  "enableInstallTelemetry": false
}
```

### Helper tools

`fd` (fd-find) and `ripgrep` are pre-installed via apt in the Docker image so pi doesn't need to download them at runtime (the Hive MITM proxy would corrupt the downloads).

---

## 5. Agents (historical)

### Historical agents (ACMM L5)

| Agent | Mode | Cadence | Role |
|-------|------|---------|------|
| **supervisor** | ADVISORY | 5m | Agent health monitoring, sweep analysis, stall detection |
| **scanner** | ISSUES_AND_PRS | 4h | Issue triage, PR dispatch, merge management |
| **ci-maintainer** | ISSUES_AND_PRS | 4h | CI/CD health, workflow fixes, build monitoring |
| **quality** | ISSUES_AND_PRS | 2h | Test coverage, integration tests, quality gates |
| **sec-check** | ISSUES_AND_PRS | 4h | Security scanning, dependency audit, CVE monitoring |
| **guide** | ISSUES_AND_PRS | 4h | Documentation gaps, onboarding analysis |
| **architect** | ISSUES_AND_PRS | 4h | Cross-cutting RFCs, refactors, new features |
| **strategist** | ISSUES_AND_PRS | 4h | Experiment design, A/B testing, strategy lab |
| **brainstorm** | on-demand | — | Ideation via Inception; proposes features and architecture |

### Agent modes

| Mode | Can create issues | Can create PRs | Can merge |
|------|-------------------|----------------|-----------|
| ADVISORY | ✗ | ✗ | ✗ |
| ISSUES_ONLY | ✓ | ✗ | ✗ |
| ISSUES_AND_PRS | ✓ | ✓ (hold-gated) | ✗ |

Mode is determined by ACMM level + agent config. At L5, most agents run in ISSUES_AND_PRS.

### Agent lifecycle

1. **Boot**: Agent starts in tmux session, receives role prompt + authorized repos
2. **Kick**: Governor sends a task prompt (e.g., "scan for open issues", "check CI health")
3. **Work**: pi processes the prompt, runs tools, produces beads or GitHub issues/PRs
4. **Idle**: Agent waits for next kick
5. **Clear on kick** (`clear_on_kick: true`): `^C` kills the pi process before the next kick, wrapper restarts it fresh

### Adding a new agent

```yaml
# In hive.yaml ConfigMap, under agents:
my-agent:
  enabled: true
  backend: pi
  model: deepseek-v4-pro
  mode: ISSUES_AND_PRS
  beads_dir: /data/beads/my-agent
  clear_on_kick: true
```

Also add the agent to governor cadences for each mode:

```yaml
governor:
  modes:
    idle:
      my-agent: 4h
    quiet:
      my-agent: 4h
    busy:
      my-agent: 1h
    surge:
      my-agent: pause
```

---

## 6. ACMM levels (historical)

The ACMM (Autonomous Code Maintenance Maturity) framework defines 6 levels:

| Level | Name | Behavior |
|-------|------|----------|
| **L1** | Advisory | Advisory-only reports, no writes |
| **L2** | Issues | Can create issues, no PRs |
| **L3** | CI/CD | Issues + hold-gated PRs, merge requires human LGTM |
| **L4** | Guarded | Broader write access, more agents active |
| **L5** | Guarded Auto-Merge | Auto-merge on green CI with guardrails |
| **L6** | Full Autonomy | Unrestricted agent actions |

That historical configuration used **L5**; this is not a statement about the current spokes.

### Changing ACMM level

```yaml
# In hive.yaml ConfigMap
acmm_level: 5
```

The old procedure reset persistent state and restarted the pod; do not use it
on the current deployment or on retained backups.

---

## 7. Governor (historical)

The governor evaluates the issue queue every 5 minutes (`eval_interval_s: 300`) and switches between four modes:

| Mode | Threshold | Behavior |
|------|-----------|----------|
| **idle** | 0 issues | Slow cadences, minimal activity |
| **quiet** | ≤2 issues | Normal cadences |
| **busy** | ≤50 issues | Faster scanner, ci-maintainer still active |
| **surge** | >50 issues | Scanner every 15m, ci-maintainer paused |

### Historical cadences

```yaml
governor:
  eval_interval_s: 300
  modes:
    surge:
      threshold: 50
      scanner: 15m
      ci-maintainer: pause
      quality: pause
      sec-check: pause
      guide: pause
      architect: pause
      strategist: pause
    busy:
      threshold: 10
      scanner: 15m
      ci-maintainer: 1h
    quiet:
      threshold: 2
      scanner: 15m
      ci-maintainer: 45m
    idle:
      threshold: 0
      scanner: 4h
      ci-maintainer: 4h
```

The supervisor always runs at 5m regardless of mode.

---

## 8. Configuration (historical)

### Backends (backends.conf)

The `backends.conf` in the ConfigMap defines supported AI backends. Adding a new backend requires entries in three places:

1. `KNOWN_BACKENDS` list
2. `backend_binary()` — maps backend name to binary in PATH
3. `backend_perm_flag()` — permission flag (pi returns empty — no permission popups)

The old supported list was `claude copilot bob gemini codex amazonq goose aider pi`.

### Agent configuration (hive.yaml)

```yaml
agents:
  supervisor:
    enabled: true
    backend: pi
    model: deepseek-v4-pro
    beads_dir: /data/beads/supervisor
    clear_on_kick: true
```

### Persistent state

Two locations store state that survives pod restarts:

- **`/data/hive-state.json`** — Governor mode, agent overrides, kick history, cadence overrides
- **`/data/agent-configs/*.yaml`** — Per-agent persistent config (backend, model, mode, enabled, display name)

Persistent overrides could cause stale values in that deployment. Do not copy
its old state-reset and backend-rewrite commands to the current deployment.

---

## 9. Building the image (historical)

The former CI workflow built `ghcr.io/hanthor/hive:latest`; an older Kaniko
job was also used. Neither is a current deployment procedure.

### What's in the image

- **Base**: `node:24-slim`
- **Runtime deps**: bash, curl, git, gosu, iptables, jq, procps, python3, tmux, `fd-find`, `ripgrep`
- **Go binaries**: hive (agent manager), bd (bead CLI) — cross-compiled from `kubestellar/hive` v2
- **Node.js proxy**: Dashboard UI + SSE, serves on :3001
- **pi**: `@earendil-works/pi-coding-agent` installed via npm
- **pi-wrapper.sh**: Replaces `/usr/local/bin/pi` with the tmux interface wrapper
- **gh CLI**: GitHub CLI with wrapper for App token auth
- **Entrypoint**: UID isolation, tmux setup, config backup, App token generation

---

## 10. Historical operations

Operators inspected the old pod's health, tmux panes, pi processes and logs
with `kubectl`. Those commands targeted the retired Kubernetes deployment;
the read-only Compose inventory at the top of this page is the current starting
point instead.

### Historical restarts and state resets

The former procedure restarted the pod and sometimes reset persistent state.
It is not a recovery procedure for Spindle; do not reset retained data.

---

## 11. Historical troubleshooting

| Symptom | Check |
|---------|-------|
| ImagePullBackOff | The home cluster once encountered IPv6 timeouts to ghcr.io |
| Agent CLI crashed | Check `ps aux \| grep pi` — should see 9 pi processes |
| Agent stuck in ADVISORY mode | Historical state-file ACMM overrides |
| Dashboard shows old backend/model | Historical `/data/agent-configs/*.yaml` overrides |
| No kicks sent | Governor eval cycle: 5min. Agent cadences vary per mode |
| Issues not created | GitHub App installation and authentication were relevant |
| "CLI did not reach input prompt" | pi is mid-response when kick arrives. Normal — agent will pick up next kick |
| fd/ripgrep download errors | pi can't download tools through MITM proxy. Pre-installed in Docker image |
| "backend binary not found" | Missing binary in PATH. Check `backends.conf` and verify wrapper is at `/usr/local/bin/pi` |
| "failed to persist config" | Read-only ConfigMap mount. Cosmetic — config is cached in memory |

### Historical agent issues

**Agent shows bare bash shell:**
- pi process died or never started
- Check: `tmux capture-pane -t hive-scanner -p | tail -5`
- Should show pi's footer (`deepseek-v4-pro • high`), not `$` bash prompt

**Agent stuck at `/clear`:**
- Hive sent `/clear` to reset the agent before a kick
- Agent processed it but new kick hasn't arrived yet
- Wait for next governor cycle

**Agent mode mismatch:**
- The state file held persistent mode overrides in that deployment.

---

## 12. GitHub App (historical)

Hive authenticates to GitHub via a GitHub App installed on `tuna-os` (App and installation IDs are in the `hive-secrets` Secret).

### Token generation

The entrypoint generates an installation token on startup and caches it at `/var/run/hive-metrics/gh-app-token.cache`. Agents access it via `$GH_TOKEN`.

### Required permissions

| Permission | Scope | Why |
|------------|-------|-----|
| `contents: read` | Repo | Read code, files |
| `contents: write` | Repo | Create branches, push commits for PRs |
| `issues: write` | Repo | Create and update issues |
| `pull_requests: write` | Repo | Create PRs |
| `metadata: read` | Repo | Basic repo access |
| `security_events: read` | Repo | Dependabot alerts (sec-check agent) |

### Rate limits

- GitHub App: 15,000 req/hr (shared across all installations)
- Personal Access Token: 5,000 req/hr

The App gives Hive its own rate limit pool, separate from personal API usage.

### Permission changes (historical)

GitHub App permission changes required re-acceptance by the installation. Do
not use the old Kubernetes restart procedure to apply them.

## Images and upgrades on the former AWS cluster

On 2026-09-24 the AWS Hives used stock upstream images
(`ghcr.io/hivecommons/hive`, `hive-hub`), not the `tuna-os/hive` fork.
The configuration described below was subsequently superseded by the
`HiveRelease` operator controller before the cluster was terminated.

| Hive | Namespace | Branding |
|---|---|---|
| hive.reilly.asia (canary) | `hive-hanthor` | none |
| reef.tunaos.org | `hive-reef` | REEF |
| school.tunaos.org (legacy alias hive.tunaos.org) | `hive` | SCHOOL |
| hub.tunaos.org | `hive-hub` | — |

At that time the `hive-upgrade` CronJob checked upstream v5 releases daily,
upgrading one Hive at a time with a soak and rollback. It was later deleted in
favor of the operator's `HiveRelease` controller. The retained
[`upgrade` history](https://github.com/hanthor/dotfiles/blob/master/talos-k8s/hive/upgrade/README.md)
is not an active upgrade runbook.

The old `hive-fork-{switch,verify,drift,ai-check}` CronJobs had been suspended;
they do not run on the terminated AWS cluster.
