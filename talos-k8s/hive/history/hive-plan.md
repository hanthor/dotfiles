# Hive Deployment Plan — Talos K8s Cluster

## Summary

Deploy [hive](https://github.com/kubestellar/hive) (v2 branch — Go rewrite) as a Kubernetes-native workload
on the 2-node Talos cluster. Hive is a 24/7 supervisor runtime for long-running AI agents.

**Approach**: K8s namespace (`hive`) using upstream v2 branch K8s manifests as a starting point.
The v2 branch is a major Go rewrite with:
- Go-based `hive` binary (agent manager, scheduler, governor, dashboard API)
- Node.js proxy (dashboard UI on :3001, API on :3002)
- ttyd web terminal (:7681)
- Per-agent UID isolation, knowledge system, MITM proxy

**Base image**: Build from upstream v2 `Dockerfile` + goose CLI for DeepSeek.

**Target node**: `bihar` (control-plane, healthy; 3% CPU / 18% mem).

## Architecture (v2)

```
┌──────────────────────────────────────────────────────────────────┐
│ Namespace: hive                                                   │
│                                                                   │
│  ┌───────────┐  ┌──────────────┐  ┌──────────┐                   │
│  │ Secret    │  │ ConfigMap    │  │ PVC      │                   │
│  │ hive-     │  │ hive.yaml    │  │ hive-data│                   │
│  │ secrets   │  │ (agent cfg)  │  │ (10Gi)   │                   │
│  └─────┬─────┘  └──────┬───────┘  └────┬─────┘                   │
│        │               │               │                         │
│        ▼               ▼               ▼                         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Deployment: hive                                          │   │
│  │ Image: ghcr.io/hanthor/hive:latest (custom, v2 + goose)   │   │
│  │                                                            │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐                │   │
│  │  │ hive     │  │ proxy    │  │ ttyd     │                │   │
│  │  │ Go binary│  │ node.js  │  │ web term │                │   │
│  │  │ :3002    │  │ :3001    │  │ :7681    │                │   │
│  │  └──────────┘  └──────────┘  └──────────┘                │   │
│  │                                                            │   │
│  │  AI Backend: goose CLI → DeepSeek API (deepseek-v4-pro)   │   │
│  │  Agents: supervisor, scanner, reviewer                     │   │
│  └─────────────────────┬────────────────────────────────────┘   │
│                        │                                         │
│  ┌─────────────────────▼────────────────────────────────────┐   │
│  │ Service: hive (ClusterIP)                                 │   │
│  │ :3001→dashboard  :3002→api  :7681→ttyd                   │   │
│  └─────────────────────┬────────────────────────────────────┘   │
│                        │                                         │
│  ┌─────────────────────▼────────────────────────────────────┐   │
│  │ Ingress: hive.manatee-basking.ts.net (Tailscale)          │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

## Watched Repos

| Repo | Description |
|------|-------------|
| `hanthor/dotfiles` | Ansible-driven dotfiles + infra |
| `tuna-os/tunaos` | Tuna OS |
| `tuna-os/tacklebox` | Tacklebox |

## AI Backend: DeepSeek via goose

Hive v2 supports `goose` as a backend (already mapped in `backends.conf` + `agent-launch.sh`).
Goose is a Rust-based open-source AI agent CLI from the Agentic AI Foundation.

**Two viable paths for DeepSeek:**

| Path | How | Complexity |
|------|-----|------------|
| **OpenRouter** (recommended) | goose natively supports OpenRouter → route to DeepSeek models | Simple: set `GOOSE_PROVIDER=openrouter` + `OPENROUTER_API_KEY` |
| **openai_compatible** | goose supports OpenAI-compatible endpoints → point at `api.deepseek.com` | Medium: set `GOOSE_PROVIDER=openai_compatible` + endpoint + key |

**Model**: `deepseek-v4-pro` (user specified)

**Both options need**: goose CLI binary installed in the Docker image.

## Deployment Steps

### Phase 1: Custom Docker Image
1. ~~Research goose + DeepSeek~~ ✅ Done
2. Write `Dockerfile` — based on upstream v2 Dockerfile, adds goose CLI
3. Build & push to `ghcr.io/hanthor/hive:latest`

### Phase 2: K8s Manifests
4. Write `talos-k8s/hive.yaml` based on upstream `v2/deploy/k8s/` manifests:
   - Customize `hive.yaml` ConfigMap for our 3 repos + DeepSeek backend
   - Configure Secret with API keys
   - Adapt deployment (nodeSelector → bihar, remove kustomize)
   - Add Tailscale Ingress

### Phase 3: Deploy & Verify
5. Build image, apply manifests, verify pod health
6. Set up ntfy notifications
7. User sets up GitHub App

## Open Decisions

| # | Question | Status |
|---|----------|--------|
| 1 | OpenRouter vs direct DeepSeek API for goose? | **Recommend OpenRouter** (simpler) |
| 2 | DeepSeek model: `deepseek-v4-pro` | ✅ Confirmed |
| 3 | Agents: supervisor + scanner + reviewer (3) | ✅ Confirmed |
| 4 | ntfy topic | User task |
| 5 | GitHub App | User task (post-deploy) |

## File Inventory (to be created)

```
talos-k8s/
├── Dockerfile              # Custom image (v2 base + goose)
└── hive.yaml               # All K8s resources for hive namespace
```
