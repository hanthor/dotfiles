# Hive — AI Agent Supervisor

## Current deployment: Spindle VPS

Two Hive spokes, **school** and **reef**, and their **hub** run as Docker
Compose services on the [Spindle VPS](../servers/spindle-vps/README.md) under
`/srv/hives` (`ubuntu@100.113.75.88` over Tailscale). Caddy routes
[school.tunaos.org](https://school.tunaos.org),
[reef.tunaos.org](https://reef.tunaos.org) and
[hub.tunaos.org](https://hub.tunaos.org) to them. Everything below was read from
the host on 2026-11-13 unless marked *unverified*. Container state alone does
not prove agents are healthy; see [Checking health](#checking-health).

This section is the current operations guide. The
[archived cluster guide](#archived-cluster-guide) after it describes the retired
Kubernetes deployment and must not be applied here.

### Layout

```text
/srv/hives/
├── compose.yaml            # services: hub, hub-front, school, reef (network spindle_default)
├── compose.override.yaml   # pins the running binary/dashboard, memory limits, session pool
├── .env                    # secrets and NTFY topic (mode 600; never print or commit)
├── bin/hive-<sha>          # fork builds; compose.yaml mounts bin/hive, the override re-pins one
├── <spoke>/config/hive.yaml        # seed, mounted read-only at /etc/hive
├── <spoke>/data/hive.yaml.runtime  # live config, in the spoke's /data volume
├── hub/  hub-front/        # hub config/data/secrets; static front page
└── backups/                # timestamped copies of every config and data snapshot
```

- **Seed vs runtime.** The spoke starts from the seed and persists its live
  configuration to `data/hive.yaml.runtime`, which then wins. Hive can rewrite
  the runtime file (dashboard changes, ACMM level), so the two files drift:
  reef's runtime is ACMM 6 while its seed says 5. Edit the **seed and the
  runtime** for anything you want to stick, then verify the parsed result.
- **Binary.** `compose.yaml` bind-mounts `bin/hive` over `/usr/local/bin/hive`;
  on 2026-11-13 `compose.override.yaml` re-pins hub, school and reef to
  `bin/hive-2ef7dc7c0` (a `tuna-os/hive` fork build on upstream v6) and mounts a
  matching dashboard HTML on the spokes. The image tag
  (`ghcr.io/hivecommons/hive:v6-latest`, hub `hive-hub:v6-latest`) does not
  identify the running code; the header of the override file is the change log
  and rollback note.
- **Agents.** All agents use the `claude` backend (sonnet, opus, haiku and
  fable tiers) on both spokes; the seed's `backends.allow` also lists `omp`
  (and `muse` on school). Runtime model assignments differ from the seed's.
- **Dashboard.** `dashboard.authorized_users` is `hanthor:owner`. The
  `dashboard.auth_token` in the runtime file and the GitHub App key are
  secrets: never print, paste or commit them.

### Roster

Each non-empty `tuna-os` repo is in exactly one hive, except the deliberate
exclusions below (state of 2026-11-13; `xfce-linux` was renamed `brussels`).

| Hive | Repos |
|---|---|
| **school** (21) | tunaos, tromso, tacklebox, brussels, tunaos-packages, wootc, fisherman, bootc-installer, bootc-migrate, bootsahi, remora, bst-ci, iso-builder, branding, homebrew-tap, scoop-bucket, athens, docs, .github, bluefin-cli, tuna-desktop |
| **reef** (22) | Tavern, corral, flatpak-index, gtk-office-suite, blueshell, dualcut, gnome-hive-monitor, hive, mandelbrot, mariner, protota, spindle, PaperWM, compass, ccleft, hive-operator, quickcast, postcard, lifafa, tuna-mail, proton-unofficial-sdk, tuta-unofficial-sdk |
| **excluded** | iced, libcosmic, rust-atomicwrites, rdocx, changelog-action (patch-carrier forks, no issues); flatpark (excluded from automation); publish-proof (empty) |

The roster is two lists, `project.repos` and `dashboard.matrix.repos`, and both
must match in **both** files of the spoke (four edits per change). The seed uses
either bare names or `tuna-os/<name>` in `project.repos` (reef bare, school full);
the runtime file uses bare names there and `tuna-os/<name>` in the matrix. Keep
whatever style the file already has. `school` also has a separate
`revert_sheriff.repos` list (shadow mode); it is not part of the roster.

As of 13:01Z on 2026-11-13 the reef **seed** lacked `postcard` (21 repos) while
the runtime listed it (22); the intent of that seed edit is unverified.

### Identity

| Hive | GitHub App | App id |
|---|---|---|
| school | `hanthor-hive-agent` | 3942065 |
| reef | `tuna-reef-hive` | 5546574 |

Both set `github.app_authored_prs: true` and `project.ai_author: ""`, so PRs and
comments come from the App's `[bot]` account, not from a human or AI-author
trailer. Each hive lists the other App in `github.additional_bot_logins`. Both
Apps are installed on every org repo *(per the maintainer; not checkable from
the host)*, so **adding a repo needs only a roster edit**, no App change.

Both hives set `sentinel.exempt_logins: [renovate[bot]]`. Sentinel's
`sensitive_path` rule flagged every dependency bump and re-flagged after each
rebase. The alternative, `auto_merge.trusted_bot_authors`, would also let Hive
auto-merge Renovate major bumps, which the org forbids.

### Adding or moving a repo

1. Pick the hive: school for the OS, packaging, installer and org-level repos;
   reef for apps, libraries and the Matrix/Hive tooling (see the table). Check
   the repo is in no other roster.
2. Apply the [safe edit procedure](#safe-edit-procedure) with `add <repo>` on
   the target hive's two files. To **move** a repo, also run `remove <repo>` on
   the old hive's two files, in the same maintenance window, so it is never in
   both or neither.
3. Re-parse both files and check the list lengths and that the new repo shows
   up on the hive's dashboard; no App installation step is needed.

### Safe edit procedure

More than one operator edits `/srv/hives` (including agents). Re-read the files
immediately before editing and never overwrite a file you read earlier.

Do **not** `docker compose up` a spoke that is running to apply config: it
triggered a container-rename bug. Remove the container first:

```bash
cd /srv/hives
docker compose rm -f -s reef          # stop and remove the spoke container only
python3 hive-roster.py add NAME reef/config/hive.yaml reef/data/hive.yaml.runtime
docker compose up -d --no-deps reef   # recreate only this spoke
docker ps --filter name=hives-        # verify: Up, and the right name
```

The edit step must (a) write a timestamped copy of each file into
`/srv/hives/backups/` first, (b) parse the YAML before and after, and (c) abort,
writing nothing, if anything other than the intended change would differ. This
helper does that for roster edits (save it as `/srv/hives/hive-roster.py` and
run it from `/srv/hives`; it needs PyYAML):

```python
#!/usr/bin/env python3
"""hive-roster.py add|remove REPO FILE...  (run with the spoke container removed)"""
import datetime, shutil, sys, yaml

ORG = "tuna-os"
BACKUPS = "/srv/hives/backups"
PATHS = (("project", "repos"), ("dashboard", "matrix", "repos"))

def seq_node(root, path):
    node = root
    for key in path:
        node = next(v for k, v in node.value if k.value == key)
    return node

def edit(text, op, repo):
    lines = text.split("\n")
    root = yaml.compose(text)
    # bottom-most list first so earlier line numbers stay valid
    seqs = sorted((seq_node(root, p) for p in PATHS), key=lambda n: -n.start_mark.line)
    for seq in seqs:
        full = seq.value[0].value.startswith(ORG + "/")
        item = f"{ORG}/{repo}" if full else repo
        hit = [n for n in seq.value if n.value in (repo, f"{ORG}/{repo}")]
        col, last = seq.value[0].start_mark.column, seq.value[-1].start_mark.line
        if op == "add" and not hit:
            lines.insert(last + 1, " " * (col - 2) + "- " + item)
        elif op == "remove":
            for n in sorted(hit, key=lambda n: -n.start_mark.line):
                del lines[n.start_mark.line]
    return "\n".join(lines)

def main(op, repo, *files):
    assert op in ("add", "remove") and files
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    new = {}
    for f in files:
        old = open(f).read()
        want = yaml.safe_load(old)
        for path in PATHS:
            d = want
            for k in path[:-1]:
                d = d[k]
            style = d[path[-1]][0].startswith(ORG + "/")
            item = f"{ORG}/{repo}" if style else repo
            d[path[-1]] = [x for x in d[path[-1]] if x not in (repo, f"{ORG}/{repo}")]
            if op == "add":
                d[path[-1]].append(item)
        text = edit(old, op, repo)
        if yaml.safe_load(text) != want:
            sys.exit(f"{f}: unrelated change detected, aborting (nothing written)")
        new[f] = text
    for f, text in new.items():
        shutil.copy2(f, f"{BACKUPS}/{f.replace('/', '-')}.{stamp}")
        open(f, "w").write(text)

main(*sys.argv[1:])
```

The script was exercised only on synthetic copies of the two file styles, not
on the live files. Backups from the 2026-11-13 edits are
`backups/*.20261113T040153Z` (sentinel exemption) and
`backups/*.roster.20261113T125525Z` (roster); to roll back, remove the
container, restore both files of the spoke from the same stamp, and `up` it.
Rolling back the binary is described in the header of `compose.override.yaml`.

### Operating from GitHub

You rarely need the host. On a hive-managed issue or PR:

- `/hive decision <instruction>` records a maintainer decision for the agents;
  `/hive approve` lifts Hive's own `needs-human` hold on a PR; `/fixed` tells
  Hive an issue is resolved.
- On PRs that Hive did not author, a GitHub review (approve or request changes)
  is honoured.
- When Hive un-parks an issue it removes the `blocked` label itself. Decision
  comments written by the maintainer's agent start with
  `Decision (for @hanthor):`.

(The command names are present in the running binary and the usage comes from
the maintainer; their exact semantics were not exercised for this page.)

### Checking health

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://school.tunaos.org/api/health   # 200
curl -s -o /dev/null -w '%{http_code}\n' https://reef.tunaos.org/api/health     # 200
curl -s https://hub.tunaos.org/api/fleet-stats                                  # hub: /api/health is 404
ssh ubuntu@100.113.75.88 'docker ps --filter name=hives-'
```

For authenticated status from the host, call the API inside the container with
the container's own token, so it is never printed:

```bash
ssh ubuntu@100.113.75.88 'docker exec hives-school-1 sh -c \
  "curl -sS -H \"X-Hive-Internal: \$HIVE_DASHBOARD_TOKEN\" http://127.0.0.1:3002/api/status"' \
  | jq '.agents[] | {name, paused, state}'
```

Agents that show `stopped` are normal between governor kicks; check authored
PRs and issues (`gh search prs --author "hanthor-hive-agent[bot]"` and
`"tuna-reef-hive[bot]"`) to see whether a hive is producing.

### Known limits

- **Memory.** Spokes are capped at 2560 MB each (raised from 2 GB on 2026-11-13
  after hive was OOM-killed during rustc/govulncheck builds). The hub allows 2
  concurrent shared-pool agent sessions across both spokes (about 400 MB per
  Claude session; the host had about 5 GB free and no swap). Do not raise either
  without revisiting the host's headroom.
- **Hive's own CI** for `tuna-os/hive` is blocked by GitHub ("Actions has been
  disabled"; a support ticket is pending), so fork builds are not CI-verified.
- **Reply spam**: upstream
  [hivecommons/hive#17512](https://github.com/hivecommons/hive/pull/17512)
  (draft) fixes Hive repeating its un-park replies because it does not
  recognise its own earlier reply when posting as an App login.
- **Concurrent edits and drift**: see the layout notes above; verify after every
  restart that the parsed seed and runtime agree on the roster.
- Not covered here: the hub's own config, the `omp-auth-broker` user service
  the spokes call (`OMP_AUTH_BROKER_URL`), and Caddy routing, which were not
  re-inspected for this page. The `hive.reilly.asia` hanthor spoke of the old AWS
  cluster has no container on this host; its current status is unverified. The
  [hive_ops role](../roles/hive_ops.md) targets the retired cluster, not this
  deployment.

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
