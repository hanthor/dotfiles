# KubeStellar Hive Contributor

KubeStellar Hive contributor pod running on the Talos cluster, backed by Lemonade's Qwen3.6-27B model.

> **Postmortem:** See [cluster-fixes-2026-06.md](cluster-fixes-2026-06.md) for the June 2026 death-loop incident and all fixes applied.

Uses the upstream `ghcr.io/kubestellar/hive-contributor` image (pre-built with goose + gh + scripts).

## Setup

```bash
# 1. Register with the hub
cd /tmp/hive
export HIVE_HUB=wss://hosted-projectbluefin-knuckle-gjvq.hive.kubestellar.io/contribute
just contribute-register

# 2. Create K8s secrets
kubectl create secret docker-registry ghcr-secret \
  --docker-server=ghcr.io \
  --docker-username=<github-user> \
  --docker-password="$(gh auth token)"

kubectl create secret generic kubestellar-hive-secrets \
  --from-literal=gh-token="$(gh auth token)" \
  --from-literal=registration-token="$(grep HIVE_REGISTRATION_TOKEN ~/.config/hive/contributor.env | cut -d= -f2)"

# 3. Deploy
kubectl apply -f manifest.yaml
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  kubestellar-hive pod (goose agent)                 │
│                                                     │
│  contributor-agent.sh                               │
│    ├─ contributor-relay.sh (WebSocket → hub)        │
│    └─ goose (in tmux session)                       │
│         │                                           │
│         └─ POST /v1/chat/completions ───────────────┼───┐
│              model: Qwen3.6-27B-GGUF                │   │
└─────────────────────────────────────────────────────┘   │
                                                          │
┌─────────────────────────────────────────────────────────┘
│  Lemonade (karnataka)
│  https://lemonade.manatee-basking.ts.net/v1
│  Qwen3.6-27B-GGUF (18.5GB, 262K ctx, vision, tool-calling)
└─────────────────────────────────────────────────────────
```
