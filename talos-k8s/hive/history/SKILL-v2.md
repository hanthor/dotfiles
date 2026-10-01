# Skill: Hive Operations

Deploy, configure, and debug hive — the 24/7 AI agent supervisor running on the Talos K8s cluster. Hive watches GitHub repos, triages issues/PRs, and creates advisory reports using pi + DeepSeek.

## When to use

- Checking if hive is dormant or working (health check)
- Debugging agent crashes, kick failures, or governor issues
- Adding/removing repos from hive's watch list
- Adjusting ACMM levels, agent modes, or governor thresholds
- Investigating stuck agents (git hangs, proxy issues, prompt delivery)
- Deploying or updating the hive pod on the cluster

## Quick reference

### Namespace and resources
All hive resources live in the `hive` namespace on the Talos cluster:
```
hive (namespace)
├── deploy/hive          — main pod
├── svc/hive             — ClusterIP :3001 (dashboard), :3002 (API), :7681 (ttyd)
├── ingress/hive         — Tailscale ingress → hive.manatee-basking.ts.net
├── configmap/hive-config — hive.yaml (project config, agents, governor)
├── secret/hive-secrets  — DEEPSEEK_API_KEY, GH_APP_ID, gh-app-key.pem
├── pvc/hive-data        — 10Gi persistent state (beads, logs, repos)
└── secret/ghcr-auth     — GHCR pull credentials
```

### Files
```
talos-k8s/hive/
├── hive.yaml              — K8s manifests (namespace, deploy, svc, ingress, configmap)
├── Dockerfile             — Custom image (hive v2 + pi + pi-wrapper.sh)
├── pi-wrapper.sh          — Wrapper: Hive tmux interface → pi interactive TUI
├── pi-marker.patch        — Adds "pi" to hive's cliPaneMarkers (source patch)
├── deepseek-chat.py       — Python fallback (direct DeepSeek API, unused with pi)
├── build-job.yaml         — Kaniko build job (deprecated, use CI now)
├── auto-close-boot-reports.yml — GH Action to auto-close boot reports after 7 days
├── hive-plan.md           — Deployment plan
└── README.md              — Architecture & troubleshooting
```

### Architecture decisions

- **goose + DeepSeek**: Goose with custom_deepseek provider; no proxy or litellm needed
- **GitHub App**: App ID 3942065 on tuna-os org (15K req/hr vs PAT 5K)
- **IPv4 /etc/hosts**: Talos forces IPv4 for ghcr.io to fix pull timeouts
- **ACMM L6**: Full autonomy (issues + PRs + auto-merge on scanner)
- **9 goose agents** — all using DeepSeek v4-pro

## Health check — is hive working?

### The 30-second check
```bash
# 1. Is the pod running?
kubectl get pods -n hive -o wide

# 2. Are kicks flowing? (look for "agent kicked" vs "failed to send kick")
kubectl logs -n hive deploy/hive --tail=50 | grep -E "(agent kicked|failed to send kick)"

# 3. Are agents processing? (look for "agent output signal")
kubectl logs -n hive deploy/hive --tail=100 | grep "agent output signal" | wc -l

# 4. Advisory digest timestamp
kubectl exec -n hive deploy/hive -- curl -s localhost:3001/api/status 2>&1 | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('advisoryDigest',{}).get('generated_at','?'))"
```

### Signs hive is dormant
- `"failed to send kick"` with `"CLI did not reach input prompt"` — agents can't receive kicks
- Advisory digest timestamp is > 30 min old
- All `ps aux | grep pi-real` show 0.0% CPU and 0:00 TIME
- `"agent output signal"` count is zero or only echoes kick templates

### Signs hive is working
- `"audit: agent kicked"` for all agents — kicks flowing
- `"agent output signal"` with diverse events (git_commit, git_push, advisory, test_activity)
- Advisory digest generated within last 5-10 min
- Pi processes show non-zero CPU TIME (not %)

## Debugging

### Tmux sessions
```bash
# List all agent sessions
kubectl exec -n hive deploy/hive -- tmux -S /tmp/tmux-0/default ls

# View an agent's pane (last 40 lines, with escape codes for pi status bar)
kubectl exec -n hive deploy/hive -- tmux -S /tmp/tmux-0/default capture-pane -t hive-quality -p -S -40

# Check full pane history for restart markers
kubectl exec -n hive deploy/hive -- tmux -S /tmp/tmux-0/default capture-pane -t hive-quality -p -S -500 | \
  grep -E "(DeepSeek chat ready|Environment loaded|^C\[agent)"
```

### Pi processes
```bash
# Count running pi agents
kubectl exec -n hive deploy/hive -- ps aux | grep goose | grep -v grep | wc -l
# Should be 9 (all goose-backed agents)

# Check CPU time per agent (non-zero means work has been done)
kubectl exec -n hive deploy/hive -- ps aux | grep goose | awk '{print $2, $10}'
```

### Governor state
```bash
# Governor cadence and mode
kubectl logs -n hive deploy/hive --tail=200 | grep "governor eval complete"
# Shows mode (BUSY/QUIET/IDLE/SURGE), issue count, agents_due

# Kick audit trail
kubectl logs -n hive deploy/hive --tail=200 | grep "audit: governor kicking"
# Shows each agent being kicked in sequence
```

### Advisory digest
```bash
kubectl exec -n hive deploy/hive -- curl -s localhost:3001/api/status 2>&1 | \
  python3 -c "
import sys,json
d=json.load(sys.stdin)
ad=d.get('advisoryDigest',{})
print('Generated:', ad.get('generated_at'))
print('Mode:', ad.get('mode'))
print('Total:', ad.get('total_count'))
# Latest advisory per agent
for agent, items in ad.get('by_agent',{}).items():
    if items:
        t=max(items, key=lambda x: x.get('timestamp','')).get('timestamp','?')
        print(f'  {agent}: {t[:19]}')
"
```

## Known failure modes

### 1. Git push hangs via HTTP_PROXY (most common)

**Symptom**: Agents stuck on `git push`, pane shows `Elapsed 36000s+`, CPU at 0%, `"CLI did not reach input prompt"` on kicks.

**Root cause**: The pi-wrapper sets `HTTP_PROXY`/`HTTPS_PROXY`. Git inherits these but pushes hang through the proxy. Pi blocks on the subprocess, never reaches the `❯` ready marker, wrapper loop never restarts.

**Fix**: The pi-wrapper now sets `GIT_CONFIG_COUNT` env vars to clear `http.proxy` and `https.proxy` for all git operations:
```bash
export GIT_CONFIG_COUNT=2
export GIT_CONFIG_KEY_0=http.proxy
export GIT_CONFIG_VALUE_0=
export GIT_CONFIG_KEY_1=https.proxy
export GIT_CONFIG_VALUE_1=
```

**Also**: The wrapper wraps pi-real with `timeout -s KILL 14400` (4h) so hung git processes can't permanently block an agent:
```bash
timeout -s KILL 14400 /usr/local/bin/pi-real ...
```

### 2. Goose DeepSeek API errors

**Symptom**: Goose agents start but show API errors like "provider not found" or "invalid API key".

**Check**:
```bash
# Verify goose config exists
kubectl exec -n hive deploy/hive -- cat /home/dev/.config/goose/config.yaml

# Verify API key is set
kubectl exec -n hive deploy/hive -- env | grep DEEPSEEK_API_KEY

# Test goose directly
kubectl exec -n hive deploy/hive -- sh -c 'GOOSE_PROVIDER=custom_deepseek GOOSE_MODEL=deepseek-v4-flash goose --version'
```

**Fix**: Ensure `DEEPSEEK_API_KEY` is in the hive-secrets secret and `goose-config.yaml` is in the image with the correct provider config.

### 3. Config persistence error (cosmetic)

```
ERROR: failed to persist config to yaml: open /etc/hive/hive.yaml: read-only file system
```

ConfigMap mounts are read-only. Hive tries to write back config changes. This doesn't prevent operation — config is cached in memory and state is persisted to `/data/hive-state.json`. Can be ignored.

### 4. Agents idle after kicks

**Symptom**: `"audit: agent kicked"` in logs, pane shows kick template text, but no pi output or activity.

**Check**: Verify pi processes are running (`ps aux | grep pi-real`). If CPU TIME is 0:00 for all agents, they're not processing. Check the pane for `"DeepSeek chat ready ❯"` — if missing, the wrapper loop may not have started. Restart deployment.

### 5. nfty notification errors

```
WARN: ntfy returned error: status=404
```

The NTFY_TOPIC secret may be missing or incorrect. Notifications still appear in the advisory digest on GitHub. Non-blocking.

## Common operations

### Restart hive
```bash
kubectl apply -f talos-k8s/hive/hive.yaml
kubectl rollout restart deploy/hive -n hive
kubectl rollout status deploy/hive -n hive --timeout=180s
```

### Change repos
Edit `talos-k8s/hive/hive.yaml` → `project.repos` → apply + restart

### Change ACMM level
Edit `acmm_level` in hive.yaml (top-level, not nested under `project`).

| Level | Name | Capabilities |
|-------|------|-------------|
| 1 | Dashboard | Read-only advisory |
| 2 | Advisory | Issues (advisory only, no code) |
| 3 | CI/CD | Issues + PRs, no auto-merge |
| 4 | Guarded | Issues + PRs + guarded merge |
| 5 | Autopilot | Auto-merge with review |
| 6 | Full | Full autonomy (current) |

### Add/remove an agent
Edit `agents:` section in hive.yaml. Required fields: `enabled`, `backend`, `model`, `mode`, `beads_dir`, `clear_on_kick`. Governor modes must include cadence for new agents.

### Update pi wrapper
The pi-wrapper.sh is embedded inline in the ConfigMap section of `hive.yaml`. Edit it there, apply, and restart.
