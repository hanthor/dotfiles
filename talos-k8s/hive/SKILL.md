# Skill: Hive Operations

Deploy, configure, and debug hive — the 24/7 AI agent supervisor running on the Talos K8s cluster. Hive watches GitHub repos, triages issues/PRs, and creates advisory reports using pi + DeepSeek.

## When to use

- Deploying or updating the hive pod on the cluster
- Debugging agent crashes, kick failures, or governor issues
- Adding/removing repos from hive's watch list
- Adjusting ACMM levels, agent modes, or governor thresholds
- Fixing goose compatibility or DeepSeek API issues
- Investigating why agents aren't creating issues

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

### CI workflow
`.github/workflows/hive-build.yml`:
1. Checks out kubestellar/hive v2 source
2. Cross-compiles Go binary for amd64
3. Applies pi-marker.patch to add "pi" to cliPaneMarkers
4. Builds Docker image with pi + pi-wrapper.sh
5. Pushes to `ghcr.io/hanthor/hive:latest`

## Architecture decisions

### Why pi (not goose)
Goose v1.x doesn't natively support DeepSeek, requiring a Python proxy that strips `reasoning_content` and injects `thinking:{type:disabled}`. Pi natively supports DeepSeek and has no permission popups — tools auto-execute without confirmation, making it ideal for unattended hive agents.

### Why GitHub App (not PAT)
GitHub App gives hive its own rate limit pool (15,000 req/hr) vs PAT (5,000 req/hr shared). App ID 3942065 installed on tuna-os org.

### Why IPv4 /etc/hosts fix
Talos/containerd prefers IPv6 for ghcr.io, which times out. Adding `20.207.73.86 ghcr.io` to /etc/hosts forces IPv4.

### ACMM Level 3
L3 = CI/CD: agents can create issues and PRs, but merging requires human approval. Mode override on scanner/ci-maintainer to `ISSUES_AND_PRS` because L3 defaults them to ADVISORY.

## Debugging

### Agent bare shell / not running pi
```bash
# Check pi processes
kubectl exec -n hive deploy/hive -- ps aux | grep pi-real
# Should see 3+ processes (one per agent)

# Check tmux sessions
kubectl exec -n hive deploy/hive -- sh -c '
  for s in hive-supervisor hive-scanner hive-ci-maintainer; do
    tmux -S /tmp/tmux-1001/default capture-pane -t "$s" -p | tail -3
  done
'
# Should show pi editor/prompt, not "$" bash prompt
```

### Kicks not flowing
Governor evals every 5min. Agent cadences: scanner=15min, ci-maintainer=45min (QUIET mode). Check:
```bash
kubectl logs -n hive deploy/hive | grep "governor eval"
```

### DeepSeek API issues
```bash
# Test pi directly
kubectl exec -n hive deploy/hive -- sh -c '
  pi-real -p --provider deepseek --model deepseek-v4-flash --no-session "Say hello"
'
```

### Image pull failures
Verify Talos /etc/hosts fix is still in place:
```bash
talosctl -n 192.168.0.5 get etcfilestatus | grep hosts
# Should show version 3+ (indicating the hosts patch was applied)
```

## Common operations

### Change repos
Edit `talos-k8s/hive/hive.yaml` → `project.repos` → apply + restart

### Change ACMM level
Edit `project.acmm_level` in hive.yaml. L3 = issues+PRs, L4 = broader write access, L5 = guarded auto-merge, L6 = full autonomy.

### Add a new agent
Add to `agents:` section in hive.yaml with `backend: pi`, `mode: ISSUES_AND_PRS`. Governor modes must include cadence for the new agent.

### Force a kick
The dashboard UI has a kick button. Or restart the pod — agents get boot prompts on startup.

### Update pi version
Rebuild Docker image with updated npm package. CI rebuilds on push.
