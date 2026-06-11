# Hive — 24/7 AI Agent Supervisor on Talos K8s

Based on upstream [kubestellar/hive](https://github.com/kubestellar/hive) v2 with goose CLI + DeepSeek backend.

## Changes from upstream

| Item | Upstream | Ours |
|------|----------|------|
| Agent backend | Claude / Copilot | **Goose** (open-source, DeepSeek-native) |
| Dockerfile | Installs Claude + Copilot | **+ Goose binary + DeepSeek config** |
| Config file | `goose-config.yaml` | Pre-seeded DeepSeek provider |

Everything else (Go binary, entrypoint, proxy, ttyd, agent manager, governor) is straight upstream.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│ pod: hive (bihar)                                    │
│                                                      │
│  ┌─────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │ hive    │  │ proxy    │  │ 9x goose agents    │  │
│  │ Go bin  │  │ node.js  │  │ (tmux sessions)    │  │
│  │ :3002   │  │ :3001    │  │                    │  │
│  │ (API)   │  │ (web UI) │  │ supervisor ADVISORY│  │
│  └────┬────┘  └────┬─────┘  │ scanner  ISSUES_PRS│  │
│       │            │        │ ci-maint ISSUES_PRS│  │
│       └────────────┘        │ quality  ISSUES_PRS│  │
│                              │ guide    ADVISORY  │  │
│                              │ sec-check ISSUES_PRS│ │
│                              │ architect ISSUES_PRS│ │
│                              │ strategist ISSUES_PRS││
│                              │ outreach ISSUES_PRS│  │
│                              └────────┬───────────┘  │
│                                       │              │
│  ┌────────────────────────────────────┘              │
│  │  goose → DeepSeek API (custom_deepseek provider)  │
│  │  GitHub App (tuna-os) → gh CLI for issues/PRs     │
│  └───────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────┘
         │
    ┌────▼────┐     ┌──────────────────┐
    │ GitHub  │     │ Tailscale Ingress │
    │ tuna-os │     │ hive.manatee-     │
    │ repos   │     │ basking.ts.net    │
    └─────────┘     └──────────────────┘
```

## Components

| Component | Purpose | Source |
|-----------|---------|--------|
| **hive** (Go binary) | Agent manager, governor, scheduler | kubestellar/hive v2 (unmodified) |
| **proxy** (Node.js) | Dashboard web UI + SSE | kubestellar/hive v2 (unmodified) |
| **goose** (Rust CLI) | AI agent backend | block/goose v1.x |
| **DeepSeek** | Model provider | deepseek-v4-pro via custom provider |

## Agents

| Agent | Mode | Role |
|-------|------|------|
| supervisor | ADVISORY | Orchestrates agents, sweeps, enforces cadence |
| scanner | ISSUES_AND_PRS | Triages issues, fixes bugs, auto-merges |
| ci-maintainer | ISSUES_AND_PRS | CI health, coverage, post-merge gates |
| quality | ISSUES_AND_PRS | Test coverage analysis, testing gaps |
| guide | ADVISORY | Documentation audit, contributor guides |
| sec-check | ISSUES_AND_PRS | Supply chain, secrets, dependency audit |
| architect | ISSUES_AND_PRS | Structural analysis, design recommendations |
| strategist | ISSUES_AND_PRS | Roadmap, milestone tracking, competitive analysis |
| outreach | ISSUES_AND_PRS | Ecosystem engagement, community PRs |

## Configuration

- **Repos**: tuna-os/tunaos
- **ACMM Level**: 6 (Full autonomy — issues + PRs + auto-merge)
- **Governor**: SURGE(50) → BUSY(10) → QUIET(2) → IDLE(0)
- **Goose config**: `goose-config.yaml` (DeepSeek custom provider)
- **K8s manifest**: `hive.yaml`

## Build & Deploy

```bash
# CI builds on push to dotfiles master
# .github/workflows/hive-build.yml:
#   1. Checks out kubestellar/hive v2 source
#   2. Copies our Dockerfile + goose-config.yaml
#   3. Builds image with upstream + goose + DeepSeek
#   4. Pushes to ghcr.io/hanthor/hive:latest

# Deploy:
kubectl apply -f talos-k8s/hive/hive.yaml
kubectl rollout restart deploy/hive -n hive
```

## Secrets

```bash
kubectl create secret generic hive-secrets -n hive \
  --from-literal=DEEPSEEK_API_KEY=sk-... \
  --from-literal=HIVE_GITHUB_TOKEN=ghp_... \
  --from-literal=NTFY_TOPIC=your-ntfy-topic \
  --dry-run=client -o yaml | kubectl apply -f -

# GitHub App (post-setup):
kubectl create secret generic hive-secrets -n hive \
  --from-literal=GH_APP_ID=3942065 \
  --from-literal=GH_APP_INSTALLATION_ID=137498420 \
  --from-file=gh-app-key.pem=/path/to/key.pem \
  --dry-run=client -o yaml | kubectl apply -f -
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
kubectl exec -n hive deploy/hive -- tmux -S /tmp/tmux-0/default ls
kubectl exec -n hive deploy/hive -- tmux -S /tmp/tmux-0/default capture-pane -t hive-scanner -p
```

## Troubleshooting

| Symptom | Check |
|---------|-------|
| ImagePullBackOff | `/etc/hosts` on bihar has `ghcr.io` entry |
| Agents not kicking | `kubectl logs -n hive deploy/hive \| grep "failed to send kick"` |
| DeepSeek API errors | `kubectl exec -n hive deploy/hive -- env \| grep DEEPSEEK` |
| Goose not starting | `kubectl exec -n hive deploy/hive -- goose --version` |
| Dashboard 404 | Tailscale ingress `ts-hive-*` pod running? |

See [SKILL.md](SKILL.md) for detailed debugging procedures.
