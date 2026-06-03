# Hive Debugging Handoff — 2026-06-03

## Background

Hive is deployed in the `hive` namespace on `bihar` (Talos K8s cluster) and configured to manage `tuna-os/tunaos` and `tuna-os/tacklebox`. The user noticed the Wub UI showing "Scanning repository..." and wanted to verify Hive was running at L4 (direct issue/PR creation). Currently running at **L3** with unresolved issues.

## What was fixed

### 1. ACMM level = 1 → 3 (config YAML nesting bug)

**Root cause:** `acmm_level: 3` was nested under `project:` but the Go binary reads it at the top level.

```go
// kubestellar/hive v2/pkg/config/config.go
type Config struct {
    Project   ProjectConfig `yaml:"project"`
    ACMMLevel *int          `yaml:"acmm_level,omitempty"`  // ← top-level, NOT inside project
    ...
}
```

**Fix applied:** Moved `acmm_level: 3` from under `project` to the same indentation level as `project` in `talos-k8s/hive/hive.yaml` (commit pending). Updated ConfigMap + restarted deployment. ACMM level now reads 3.

## Current state (still broken)

### 2. Scanner & ci-maintainer mode forced to ADVISORY at L3

| Agent | Config mode | Running mode | Expected |
|-------|-------------|-------------|----------|
| scanner | `ISSUES_AND_PRS` | `ADVISORY` | `ISSUES_AND_PRS` |
| ci-maintainer | `ISSUES_AND_PRS` | `ADVISORY` | `ISSUES_AND_PRS` |
| supervisor | (none set) | `ADVISORY` | `ADVISORY` |
| quality | (pack agent) | `ISSUES_AND_PRS` | OK |
| guide | (pack agent) | `FAILED` | N/A |
| brainstorm | (on-demand) | `STOPPED` | N/A |

At L1, `isCustomMode` was `true` for scanner/ci-maintainer — mode was being read from config. At L3, `isCustomMode` is `null` — the Go binary is overriding mode. Hypothesis: the Go binary loads ACMM-level-specific agent definitions that clobber the base config.

### 3. Goose agents not processing boot/kick prompts

**All three running agents** (scanner, ci-maintainer, supervisor) are stuck:

- goose starts via `goose-wrapper.sh` → telemetry prompt answered with `y`
- goose shows `goose is ready` with blinking cursor
- Boot/kick prompt is pasted via tmux `send-keys` but goes to **bash** instead of goose

The scanner's previous session showed the exact failure pattern: `^C` killed goose (from `clear_on_kick: true`), dropping to bash, then the kick prompt text was interpreted as bash commands:

```
-bash: [agent:scanner]: command not found
-bash: 1.: command not found
-bash: You: command not found
...
```

The supervisor's current session shows similar bash errors from its kick prompt.

Current live state (all three agents):
```
goose is ready
  ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌ 0% 0/1.0M
>
```

**Hypothesis:** The `goose-wrapper.sh` pipes `y` to answer telemetry, then goose starts. But the tmux session ends up back at bash (perhaps goose exits after the bootstrap prompt, or the session routing is wrong). The kick prompt is being sent to bash instead of goose's stdin.

### 4. quality and guide agents failed

```
backend copilot not found in PATH: exec: "copilot": executable file not found in $PATH
```

These are pack agents loaded at L3 that expect the Copilot CLI backend, which isn't installed in the image. The `goose-wrapper.sh` replaces `/usr/local/bin/goose` but there's no `copilot` wrapper.

### 5. Config persistence error (cosmetic)

```
ERROR: failed to persist config to yaml: write /etc/hive/hive.yaml: read-only file system
```

ConfigMap mounts are read-only. The Go binary tries to write back config changes. This doesn't prevent operation (config is cached in memory) but means runtime config changes are lost on restart. The entrypoint has a backup/restore mechanism (`/data/hive.yaml.bak`) that mitigates this.

## How to reproduce / debug

```bash
# Dashboard API
curl -sk https://hive.manatee-basking.ts.net/api/status | jq .

# Pod access
kubectl exec -n hive deploy/hive -- bash

# See agent tmux sessions (as dev user)
su -s /bin/bash dev -c "tmux -S /tmp/tmux-1001/default list-sessions"
su -s /bin/bash dev -c "tmux -S /tmp/tmux-1001/default capture-pane -t hive-scanner -p -S -200"

# Attach to an agent session
su -s /bin/bash dev -c "tmux -S /tmp/tmux-1001/default attach -t hive-scanner"

# Logs
kubectl logs -n hive deploy/hive --tail=100 -f
```

## Key files

| File | Purpose |
|------|---------|
| `talos-k8s/hive/hive.yaml` | Full K8s manifest (ConfigMap + Deployment + Service + Ingress) |
| `talos-k8s/hive/goose-wrapper.sh` | Wraps goose binary, answers telemetry prompt via `printf 'y\n' \| script` |
| `talos-k8s/hive/build-job.yaml` | Kaniko job that builds hive image from `kubestellar/hive` v2 branch |
| `kubestellar/hive` v2 branch | Upstream Go binary source |
| `/usr/local/bin/entrypoint.sh` (in container) | Startup script: UID isolation, tmux setup, proxy, ttyd |
| `/usr/local/bin/agent-launch.sh` (in container) | Unified agent launcher for goose/copilot/claude backends |
| `/usr/local/bin/hive-config.sh` (in container) | Config reader sourced by scripts |
| `/opt/hive/examples/acmm/l{1..6}.md` | ACMM policy files injected into agent prompts |

## Next steps (recommended order)

1. **Fix goose prompt delivery** — highest priority. Investigate why boot/kick prompts land in bash instead of goose. Check:
   - Does goose stay running after bootstrap, or does it exit?
   - Is tmux `send-keys` targeting the correct pane?
   - Does `clear_on_kick` send `^C` at the wrong time?
   - Try attaching to a scanner tmux session and manually sending the bootstrap prompt

2. **Fix agent modes at L3** — scanner and ci-maintainer should be `ISSUES_AND_PRS`.
   - Check if the Go binary loads ACMM pack definitions that override agent config
   - Check `AgentConfig.ACMMLevels` field — if set, it may gate which agents are active
   - Try setting `acmm_levels: [3,4,5,6]` on scanner/ci-maintainer agent configs

3. **Fix quality/guide backends** — either install Copilot CLI in the image, or change their backend to goose, or disable them

4. **Go to L4** — after agents are working at L3, bump to 4 by changing `acmm_level: 4` in `talos-k8s/hive/hive.yaml` and applying

5. **Config persistence** — consider `emptyDir` + init container that copies ConfigMap to writable location, to silence the error

## Advisory issue

- `tuna-os/tunaos#113` — created by `app/hanthor-hive-agent`, labeled `hive/advisory`
- No findings posted yet (agents aren't doing work)
- `dotfiles#24` — same pattern for the dotfiles repo (no longer configured)

## Git context

Repo: `hanthor/dotfiles`
Branch: `master` (implied)
Recent hive commits (most recent first):
- `420ea85` — fix: remove double exec from pipe in goose-wrapper.sh
- `ba41382` — fix: goose wrapper — printf y | script, TTY for tmux send-keys
- `ace4236` — docs: hive README + SKILL.md
- `7d50e07` — fix: simplify goose wrapper — direct pipe, no script TTY
- `5afe4d2` — feat: auto-close boot report issues after 7 days
- `a0c4da7` — fix: remove dotfiles, focus on tuna-os repos only
- `f748a4c` — feat: ACMM L3 with ISSUES_AND_PRS mode on scanner and ci-maintainer
