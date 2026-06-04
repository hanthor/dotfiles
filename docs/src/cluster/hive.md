# Hive — 24/7 AI Agent Supervisor

> **Hive** is an open-source AI agent orchestration system running on the Talos K8s cluster. A fleet of specialized agents autonomously maintain the `tuna-os/tunaos` repository — triaging issues, analyzing code, and creating PRs. A governor dynamically adjusts agent pace based on issue queue depth.

## Table of contents

1. [Architecture](#1-architecture)
2. [What Hive does](#2-what-hive-does)
3. [Deployment](#3-deployment)
4. [AI backend: pi + DeepSeek](#4-ai-backend-pi--deepseek)
5. [Agents](#5-agents)
6. [ACMM levels](#6-acmm-levels)
7. [Governor](#7-governor)
8. [Configuration](#8-configuration)
9. [Building the image](#9-building-the-image)
10. [Day-to-day operations](#10-day-to-day-operations)
11. [Troubleshooting](#11-troubleshooting)
12. [GitHub App](#12-github-app)

---

## 1. Architecture

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

## 2. What Hive does

### Advisory digest

The dashboard shows agent findings — CI failures, test coverage gaps, security issues, documentation problems. Each agent produces **beads** (structured findings) that appear in the advisory digest.

### Issue creation

At ACMM L3+, agents create GitHub issues. At L4+, they can create hold-gated PRs. The **sec-check** agent scans dependencies for CVEs. The **ci-maintainer** agent monitors CI failures.

### Strategy Lab

Inception feature: describe what you want to build, and Hive scaffolds a new project with knowledge base facts and spec-kit specifications. Powered by the **brainstorm** agent (on-demand).

### Knowledge Base

Agents can contribute facts to a shared knowledge base. Facts are tagged by type (pattern, gotcha, regression, decision, etc.) and searchable from the dashboard.

---

## 3. Deployment

### Namespace and resources

All Hive resources live in the `hive` namespace on the Talos cluster:

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

### Files

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

`.github/workflows/hive-build.yml` — triggers on push to `master`:

1. Clones `kubestellar/hive` v2 source
2. Applies `pi-marker.patch` and three sed patches to the Go source:
   - Adds `"pi"` to `cliPaneMarkers` (so agents aren't detected as crashed)
   - Adds `"pi": true` to `validBackends` (config validation)
   - Adds `"pi": "pi"` to `backendBinary()` (binary resolution)
3. Cross-compiles Go binary for amd64
4. Builds Docker image with pi + pi-wrapper.sh + fd/ripgrep
5. Pushes to `ghcr.io/hanthor/hive:latest`

### Secrets

```bash
kubectl create secret generic hive-secrets -n hive \
  --from-literal=DEEPSEEK_API_KEY=sk-... \
  --from-literal=GH_APP_ID=3942065 \
  --from-literal=GH_APP_INSTALLATION_ID=137498420 \
  --from-file=gh-app-key.pem=/path/to/key.pem
```

### Deploy

```bash
kubectl apply -f talos-k8s/hive/hive.yaml
kubectl rollout restart deploy/hive -n hive
```

Access: **https://hive.manatee-basking.ts.net**

---

## 4. AI backend: pi + DeepSeek

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

## 5. Agents

### Current agents (ACMM L5)

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

## 6. ACMM levels

The ACMM (Autonomous Code Maintenance Maturity) framework defines 6 levels:

| Level | Name | Behavior |
|-------|------|----------|
| **L1** | Advisory | Advisory-only reports, no writes |
| **L2** | Issues | Can create issues, no PRs |
| **L3** | CI/CD | Issues + hold-gated PRs, merge requires human LGTM |
| **L4** | Guarded | Broader write access, more agents active |
| **L5** | Guarded Auto-Merge | Auto-merge on green CI with guardrails |
| **L6** | Full Autonomy | Unrestricted agent actions |

Our Hive runs at **L5**. At each level, the Go binary enables additional pack agents and upgrades agent modes.

### Changing ACMM level

```yaml
# In hive.yaml ConfigMap
acmm_level: 5
```

After changing, nuke the persistent state to clear stale overrides:

```bash
kubectl exec -n hive deploy/hive -- sh -c 'echo "{}" > /data/hive-state.json'
kubectl rollout restart deploy/hive -n hive
```

---

## 7. Governor

The governor evaluates the issue queue every 5 minutes (`eval_interval_s: 300`) and switches between four modes:

| Mode | Threshold | Behavior |
|------|-----------|----------|
| **idle** | 0 issues | Slow cadences, minimal activity |
| **quiet** | ≤2 issues | Normal cadences |
| **busy** | ≤50 issues | Faster scanner, ci-maintainer still active |
| **surge** | >50 issues | Scanner every 15m, ci-maintainer paused |

### Current cadences

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

## 8. Configuration

### Backends (backends.conf)

The `backends.conf` in the ConfigMap defines supported AI backends. Adding a new backend requires entries in three places:

1. `KNOWN_BACKENDS` list
2. `backend_binary()` — maps backend name to binary in PATH
3. `backend_perm_flag()` — permission flag (pi returns empty — no permission popups)

Current supported: `claude copilot bob gemini codex amazonq goose aider pi`

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

If the dashboard shows stale backend/model/mode values, these files have overrides from a previous configuration. Nuke them:

```bash
kubectl exec -n hive deploy/hive -- sh -c '
  echo "{}" > /data/hive-state.json
  for f in /data/agent-configs/*.yaml; do
    sed -i "s/backend: copilot/backend: pi/" "$f"
    sed -i "s/model: claude-sonnet-4-6/model: deepseek-v4-pro/" "$f"
    sed -i "s/model: claude-opus-4-6/model: deepseek-v4-pro/" "$f"
  done
'
kubectl rollout restart deploy/hive -n hive
```

---

## 9. Building the image

### CI (recommended)

Push to `master` — the workflow builds and pushes to `ghcr.io/hanthor/hive:latest`.

### Manual (Kaniko)

```bash
kubectl apply -f talos-k8s/hive/build-job.yaml
kubectl logs -n hive -f job/hive-build
```

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

## 10. Day-to-day operations

### Check agent status

```bash
# Dashboard API
curl -sk https://hive.manatee-basking.ts.net/api/status | jq .

# Or from within the pod
kubectl exec -n hive deploy/hive -- curl -s localhost:3001/api/status
```

### View agent terminal

```bash
# List tmux sessions
kubectl exec -n hive deploy/hive -- tmux -S /tmp/tmux-1001/default ls

# View an agent's terminal
kubectl exec -n hive deploy/hive -- tmux -S /tmp/tmux-1001/default capture-pane -t hive-scanner -p -S -30
```

### Check pi processes

```bash
kubectl exec -n hive deploy/hive -- ps aux | grep "pi$"
# Should show 9 pi processes (one per active agent)
```

### View logs

```bash
kubectl logs -n hive -l app.kubernetes.io/name=hive -f --tail=100
```

### Restart

```bash
kubectl rollout restart deploy/hive -n hive
```

### Nuke persistent state

If agents have stale backend/model overrides or wrong modes:

```bash
kubectl exec -n hive deploy/hive -- sh -c 'echo "{}" > /data/hive-state.json'
# Also check /data/agent-configs/ for stale copilot/goose references
kubectl rollout restart deploy/hive -n hive
```

---

## 11. Troubleshooting

| Symptom | Check |
|---------|-------|
| ImagePullBackOff | IPv6 timeouts on ghcr.io. Verify `/etc/hosts` on bihar has `20.207.73.86 ghcr.io` |
| Agent CLI crashed | Check `ps aux \| grep pi` — should see 9 pi processes |
| Agent stuck in ADVISORY mode | Check ACMM level in state file. May need state nuke |
| Dashboard shows old backend/model | Stale overrides in `/data/agent-configs/*.yaml`. Fix with sed + state nuke |
| No kicks sent | Governor eval cycle: 5min. Agent cadences vary per mode |
| Issues not created | Verify GitHub App installed on tuna-os. Check token: `cat /var/run/hive-metrics/gh-app-token.cache` |
| "CLI did not reach input prompt" | pi is mid-response when kick arrives. Normal — agent will pick up next kick |
| fd/ripgrep download errors | pi can't download tools through MITM proxy. Pre-installed in Docker image |
| "backend binary not found" | Missing binary in PATH. Check `backends.conf` and verify wrapper is at `/usr/local/bin/pi` |
| "failed to persist config" | Read-only ConfigMap mount. Cosmetic — config is cached in memory |

### Common agent issues

**Agent shows bare bash shell:**
- pi process died or never started
- Check: `tmux capture-pane -t hive-scanner -p | tail -5`
- Should show pi's footer (`deepseek-v4-pro • high`), not `$` bash prompt

**Agent stuck at `/clear`:**
- Hive sent `/clear` to reset the agent before a kick
- Agent processed it but new kick hasn't arrived yet
- Wait for next governor cycle

**Agent mode mismatch:**
- State file has persistent mode override
- Nuke state and restart

---

## 12. GitHub App

Hive authenticates to GitHub via a GitHub App (ID **3942065**) installed on `tuna-os`.

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

### Updating permissions

1. Go to: `https://github.com/organizations/tuna-os/settings/apps/hanthor-hive-agent/permissions`
2. Add the needed permissions
3. Re-accept on the installation page
4. Restart hive: `kubectl rollout restart deploy/hive -n hive`
