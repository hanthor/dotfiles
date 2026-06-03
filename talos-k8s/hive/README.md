# Hive — 24/7 AI Agent Supervisor on Talos K8s

## Architecture

```
┌──────────────────────────────────────────────────────┐
│ pod: hive (bihar)                                    │
│                                                      │
│  ┌─────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │ hive    │  │ proxy    │  │ 3x goose agents    │  │
│  │ Go bin  │  │ node.js  │  │ (tmux sessions)    │  │
│  │ :3002   │  │ :3001    │  │                    │  │
│  │ (API)   │  │ (web UI) │  │ supervisor ADVISORY│  │
│  └────┬────┘  └────┬─────┘  │ scanner  ISSUES_PRS│  │
│       │            │        │ ci-maint ISSUES_PRS│  │
│       └────────────┘        └────────┬───────────┘  │
│                                      │              │
│  ┌───────────────────────────────────┘              │
│  │  goose v1.36 → custom_deepseek → DeepSeek API   │
│  │  GitHub App (tuna-os) → gh CLI for issues/PRs   │
│  └─────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────┘
         │
    ┌────▼────┐     ┌──────────────────┐
    │ GitHub  │     │ Tailscale Ingress │
    │ tuna-os │     │ hive.manatee-     │
    │ repos   │     │ basking.ts.net    │
    └─────────┘     └──────────────────┘
```

## Components

| Component | Purpose | Details |
|-----------|---------|---------|
| **hive** (Go binary) | Agent manager, governor, scheduler | From kubestellar/hive v2, patched with goose marker |
| **proxy** (Node.js) | Dashboard web UI + SSE | Serves on :3001, proxies to Go API :3002 |
| **goose** v1.36 | AI agent CLI | Runs in tmux sessions, uses custom_deepseek provider |
| **deepseek-chat.py** | Python fallback | Direct DeepSeek API calls if goose unavailable |

## Agents

| Agent | Mode | Role |
|-------|------|------|
| supervisor | ADVISORY | Orchestrates agents, sweeps, enforces cadence |
| scanner | ISSUES_AND_PRS | Triages issues, opens PRs, files advisory reports |
| ci-maintainer | ISSUES_AND_PRS | Code quality, coverage, post-merge health |

## Configuration

All in `talos-k8s/hive/hive.yaml`:
- **Repos**: tuna-os/tunaos, tuna-os/tacklebox
- **ACMM Level**: 3 (CI/CD — issues + PRs, no auto-merge)
- **Governor**: SURGE(50) → BUSY(10) → QUIET(2) → IDLE(0)

## Key Fixes Applied

### IPv6 → ghcr.io pull failure
Bihar couldn't pull images from ghcr.io over IPv6. Fixed by adding `/etc/hosts` entry on Talos:
```bash
talosctl -n 192.168.0.5 patch mc --patch '{
  "machine": {"network": {"extraHostEntries": [
    {"ip": "20.207.73.86", "aliases": ["ghcr.io"]}
  ]}}
}'
```

### Goose CLI compatibility
Goose v1.x removed `--no-confirm` flag and changed provider IDs. Fixed via:
- `goose-wrapper.sh`: translates old hive CLI to `goose session --max-turns 100`
- `goose-marker.patch`: adds "goose" to hive's `cliPaneMarkers` so agents aren't detected as crashed
- Provider: `custom_deepseek` (not `deepseek` or `openai_compatible`)

### Telemetry prompt
Goose v1.x shows first-run telemetry prompt that blocks stdin. Workaround: `(echo y; exec cat) | goose session`

## Build & Deploy

```bash
# CI builds on push to dotfiles master
# .github/workflows/hive-build.yml:
#   1. Cross-compiles Go binary (amd64)
#   2. Patches hive source for goose marker
#   3. Builds Docker image with goose + wrapper
#   4. Pushes to ghcr.io/hanthor/hive:latest

# Deploy:
kubectl apply -f talos-k8s/hive/hive.yaml
kubectl rollout restart deploy/hive -n hive
```

## Secrets

```bash
kubectl create secret generic hive-secrets -n hive \
  --from-literal=DEEPSEEK_API_KEY=sk-... \
  --from-literal=GH_APP_ID=3942065 \
  --from-literal=GH_APP_INSTALLATION_ID=137498420 \
  --from-file=gh-app-key.pem=/path/to/key.pem
```

## Monitoring

```bash
# Agent status
kubectl exec -n hive deploy/hive -- curl -s localhost:3001/api/status

# Logs
kubectl logs -n hive -l app.kubernetes.io/name=hive -f

# Dashboard
open https://hive.manatee-basking.ts.net

# Tmux sessions (debug)
kubectl exec -n hive deploy/hive -- tmux -S /tmp/tmux-1001/default ls
kubectl exec -n hive deploy/hive -- tmux -S /tmp/tmux-1001/default capture-pane -t hive-scanner -p
```

## Troubleshooting

| Symptom | Check |
|---------|-------|
| ImagePullBackOff | `/etc/hosts` on bihar has `ghcr.io` entry |
| Agent CLI crashed | goose wrapper working? Check `ps aux \| grep goose-real` |
| No kicks sent | Governor eval cycle: 5min, agent cadence: 15-45min |
| Issues not created | GitHub App installed on tuna-os? Token in `/var/run/hive-metrics/` |
| Dashboard 404 | Tailscale ingress `ts-hive-*` pod running? |
