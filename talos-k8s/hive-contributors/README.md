<!-- CLUSTER ACCESS NOTE: the AWS control-plane API (13.63.243.56:6443) is
     firewalled by SG sg-052a6292d2dcf728e (migration-admin-bootstrap) to a
     small IP allowlist. If kubectl times out, add your current /32 with the
     AWS_PROFILE=james-admin CLI (aws ec2 authorize-security-group-ingress),
     and REVOKE it when done. A rule tagged "james himachal kubectl <date>"
     (sgr-0eaf3d4ef8dfdd305) was added 2026-09-01 for 60.49.108.126/32. -->

# Hive persistent contributor fleet

Four **persistent** Hive contributor workers running on the AWS Talos cluster,
one per backend CLI, each subscribed to `hive.tunaos.org`:

| Deployment | `AGENT_BACKEND` | `AGENT_MODEL` (default) | Image |
|---|---|---|---|
| `claude-contributor` | `claude` | (Claude Code picks its own) | upstream `hive-contributor` |
| `agy-contributor` | `agy` | `gemini-3.7-flash-high` | upstream `hive-contributor` |
| `pi-codex-contributor` | `pi` | `openai-codex/gpt-5.6-sol` | upstream `hive-contributor` |
| `kiro-contributor` | `kiro` | (Kiro picks its own) | **custom** `ghcr.io/hanthor/hive-contributor-kiro` — ⚠️ NOT YET BUILT |

This is the cluster analogue of the four **local** podman quadlets described in
the `tunaos-contributor-fleet` skill. The difference is that these survive a
desktop being powered off — they run in Kubernetes with their own PVCs.

> The old single-worker manifest lives in `../kubestellar-hive/` (Goose +
> Lemonade, subscribed to the Project Bluefin hub). This fleet is separate and
> targets the self-hosted tuna-os hub.

## Why one Deployment per backend, not one pod with four sessions

- Independent lifecycle: one backend crash-looping never takes the others down.
- Independent persistence: each worker keeps its own CLI credential + session
  state on a dedicated PVC, so an OAuth login or a codex trust answer survives
  pod restarts and reschedules.
- Independent resource limits and logs.

"Persistent" means **identity, credentials, workspace, and session state
survive a pod restart** — not that an in-flight process is preserved across a
node failure. The upstream relay already hands an interrupted task back to the
hub (`task_failed`) so the hub can reassign it, so a restart is safe.

## Backends are already in the upstream image

`ghcr.io/kubestellar/hive-contributor:latest` ships `claude`, `codex`, `agy`,
and `pi` binaries and selects between them with `AGENT_BACKEND`. So Claude, Agy,
and Pi/OpenAI-Codex need **no custom image** — only env + secrets + a PVC.

`kiro-cli` is **not** in the upstream image, so `kiro-contributor` uses a thin
custom image (`kiro-image/Dockerfile`) that layers Kiro on top and wires it into
the relay as a claude/codex-shaped backend. See `kiro-image/README.md`.

> **Status 2026-09-02: kiro is the one worker NOT deployed.**
> `ghcr.io/hanthor/hive-contributor-kiro` returns 404 — the image has never
> been published, so `kiro.yaml` would land in `ImagePullBackOff`. Build and
> push it (see `.github/workflows/kiro-contributor-build.yml`) before applying
> that manifest. claude, agy and pi-codex are live and need no custom image.

## Identity model (READ THIS FIRST)

One **profile** per GitHub account per hub — `hanthor` is `c-be093c7b6f07` on
tunaos, `c-f20bd0da618e` on hosted-kubestellar, and `total_registered` stays 1
no matter how many backends connect. But a profile is not a slot: **all four
backends share that one profile and one registration token, concurrently.**

The hub keys live connections by a per-socket `connID` (`randomHex(8)`,
`contribute_ws.go`), *not* by contributor ID, and nothing evicts an existing
connection when another authenticates with the same profile. So N backends
presenting the SAME token get N independent connections, each assigned its own
task.

> **Proven live 2026-09-02:** claude, agy and pi-codex connected simultaneously
> on one shared token, each working a different issue (`wootc#217`, `#216`,
> `#221`) — `total_registered: 1`, three concurrent tasks.

**The real trap is re-registering, not sharing.** `POST
/api/contribute/register` for an account that already exists returns no token,
and the authenticated `reissue-token` ROTATES the stored hash — which
invalidates the token every other backend is still using and knocks them all
off. So:

- **Do** copy the existing `HIVE_REGISTRATION_TOKEN` into each
  `hive-contrib-<backend>` Secret (what `claude`/`agy` do today).
- **Don't** run `contribute-register` / `reissue-token` to "get a token for the
  new backend". That is the one action that actually breaks the fleet.

Separate GitHub identities per backend are therefore **not required**. They buy
only per-backend attribution and per-backend trust tiers, at the cost of four
accounts to keep alive.

Throughput is bounded by the profile's trust tier, not by backend count:
`hanthor` is tier `advisor`, whose limits are `0/0/0` — and **0 means
unlimited** (34 tasks were completed in a day against a `newcomer` cap of 10).

### Proven live (2026-09-01)

The `pi-codex-contributor` is deployed and **authenticated on BOTH hubs**
(`c-be093c7b6f07` on tunaos, `c-f20bd0da618e` on hosted-kubestellar), taking
real tasks, with the watchdog sidecar running — proving the interactive-relay
+ multi-hub + watchdog + PVC-seeded-OAuth design end to end. claude and agy use
the identical shape and now run alongside it on the shared token.


## Secrets (create before applying — never commit these)

Each worker reads from its own Secret `hive-contrib-<backend>`. Registration
tokens come from `just contribute-register` against the tuna-os hub; see the
upstream hive docs.

```bash
export KUBECONFIG=~/.kube/config-aws-migration
kubectl create namespace hive-contributors --dry-run=client -o yaml | kubectl apply -f -

# ── claude ──────────────────────────────────────────────────────────────
kubectl create secret generic hive-contrib-claude -n hive-contributors \
  --from-literal=HIVE_REGISTRATION_TOKEN='<token>' \
  --from-literal=GH_TOKEN="$(gh auth token)" \
  --from-literal=ANTHROPIC_API_KEY='sk-ant-...' \
  --dry-run=client -o yaml | kubectl apply -f -
# (If using Claude Code OAuth instead of an API key, omit ANTHROPIC_API_KEY and
#  seed ~/.claude interactively into the PVC — see "First-run auth" below.)

# ── agy (Antigravity / Google) ────────────────────────────────────────────
kubectl create secret generic hive-contrib-agy -n hive-contributors \
  --from-literal=HIVE_REGISTRATION_TOKEN='<token>' \
  --from-literal=GH_TOKEN="$(gh auth token)" \
  --dry-run=client -o yaml | kubectl apply -f -
# agy authenticates against a Google AI subscription; seed ~/.gemini into the
# PVC on first run (see "First-run auth").

# ── pi + OpenAI Codex ─────────────────────────────────────────────────────
kubectl create secret generic hive-contrib-pi-codex -n hive-contributors \
  --from-literal=HIVE_REGISTRATION_TOKEN='<token>' \
  --from-literal=GH_TOKEN="$(gh auth token)" \
  --from-literal=OPENAI_API_KEY='sk-...' \
  --dry-run=client -o yaml | kubectl apply -f -

# ── kiro ──────────────────────────────────────────────────────────────────
kubectl create secret generic hive-contrib-kiro -n hive-contributors \
  --from-literal=HIVE_REGISTRATION_TOKEN='<token>' \
  --from-literal=GH_TOKEN="$(gh auth token)" \
  --from-literal=KIRO_API_KEY='ksk_...' \
  --dry-run=client -o yaml | kubectl apply -f -

# ── image pull secret (all four) ──────────────────────────────────────────
kubectl create secret docker-registry ghcr-auth -n hive-contributors \
  --docker-server=ghcr.io \
  --docker-username="$(gh api user -q .login)" \
  --docker-password="$(gh auth token)" \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Deploy

```bash
export KUBECONFIG=~/.kube/config-aws-migration
kubectl apply -f talos-k8s/hive-contributors/namespace.yaml
kubectl apply -f talos-k8s/hive-contributors/claude.yaml
kubectl apply -f talos-k8s/hive-contributors/agy.yaml
kubectl apply -f talos-k8s/hive-contributors/pi-codex.yaml
kubectl apply -f talos-k8s/hive-contributors/kiro.yaml   # needs the custom image built first
```

## First-run auth for subscription backends (claude OAuth, agy)

API-key backends (pi/codex, kiro, claude-with-key) authenticate straight from
the Secret. Subscription backends that use a browser OAuth flow (Claude Code
OAuth, Antigravity) need their credential dir seeded **once** into the PVC:

```bash
POD=$(kubectl get pod -n hive-contributors -l app=claude-contributor -o jsonpath='{.items[0].metadata.name}')
# copy a working ~/.claude from your workstation into the pod's persistent home:
kubectl cp ~/.claude "hive-contributors/$POD:/home/dev/.claude"
# then restart so the relay picks it up:
kubectl rollout restart deploy/claude-contributor -n hive-contributors
```

The home dir is a PVC, so this survives restarts and reschedules.

## Health check

```bash
export KUBECONFIG=~/.kube/config-aws-migration
kubectl -n hive-contributors get pods
for d in claude-contributor agy-contributor pi-codex-contributor kiro-contributor; do
  echo "=== $d ==="
  kubectl -n hive-contributors logs deploy/$d --tail=12
done
```

Healthy log lines mirror the local fleet skill:
`Authenticated with <hub> as c-…` → good; `No task assigned … no_matching_work`
→ idle but fine; `CLI did not become ready within timeout` → wedged.

## Landmines carried over from the local fleet

- **codex/agy modal prompts on first start** (directory-trust, update nudge) —
  the upstream relay auto-dismisses the known ones (`classifyTmuxPane`). A new
  prompt shape needs adding to `blockingPromptKey()` upstream, not hand-nudging.
- **Pi needs `AGENT_MODEL=provider/model`** or it refuses to launch. Use
  `openai-codex/<model>` for the Codex integration.
- **Do not point kiro at an interactive login** — it must use `KIRO_API_KEY`
  headless auth (`kiro-cli` device flow is for humans). See `kiro-image/`.
