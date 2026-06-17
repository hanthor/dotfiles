# Cluster Fixes — June 2026

Postmortem and justification for fixes applied to the Talos K8s cluster (bihar/karnataka) after the hive-contributor death-loop incident.

## Timeline

- **Jun 13** — Contributor pod stops processing tasks after `common#646`. No logs for 2+ days.
- **Jun 15** — Diagnosed: goose network error → relay hung → no recovery. 377 restarts over 2 days.
- **Jun 16** — All fixes applied. Contributor completed `common#646` and resumed normal operation.
- **Jun 17** — Upstream relay fix merged (kubestellar/hive#1573), our patch replaced with upstream.

---

## 1. CoreDNS — upstream forwarders unreachable

### Problem

CoreDNS forwarded to `169.254.116.108` (Talos node-local link-local resolver), but the pod network (Flannel VXLAN) cannot route to link-local addresses. Result: **all external DNS broken cluster-wide**.

```
[ERROR] plugin/errors: 2 google.com. A: read udp ... -> 169.254.116.108:53: connection refused
```

### Fix

Changed CoreDNS ConfigMap `forward` from `/etc/resolv.conf` to explicit routable upstreams:

```diff
- forward . /etc/resolv.conf {
+ forward . 192.168.0.1 8.8.8.8 {
```

`192.168.0.1` is the LAN router (also listed in Talos resolvers). `8.8.8.8` is the fallback.

### Justification

Talos nodes have a local DNS resolver on `169.254.116.108` that Flannel pods can't reach. The node's `/etc/resolv.conf` is correct *for host-network processes* (like kube-flannel) but not for pod-network. CoreDNS must use routable IPs.

---

## 2. Lemonade AI Server — model swap timeouts

### Problem

Lemonade (`ghcr.io/lemonade-sdk/lemonade-server`) runs on karnataka (AMD Strix Halo, 62GB unified memory). It was configured with `max_loaded_models: 1` — only one model in VRAM at a time. The contributor used `Qwen3.6-35B-A3B-MTP-GGUF` (23.8 GB), which takes **minutes** to load from disk. Goose (the AI CLI) timed out waiting for the model to swap, then the relay falsely reported the task as complete.

### Fixes

1. **Increased `max_loaded_models` from 1 to 2** via `lemonade-config` ConfigMap
2. **Switched contributor to `Qwen3.6-27B-GGUF`** (18.5 GB — loads in 1.4s, 12-14 TPS)
3. **Added K8s health probes** (liveness/readiness/startup on `/v1/models`)
4. **Pre-warm the model** on startup so first request doesn't cold-load

### Justification

The Strix Halo has 62GB unified memory. Qwen 27B (18.5GB) + Gemma 31B (19.5GB) = 38GB — well within budget with room for KV cache. Keeping two models hot eliminates swap latency. The 27B model is within ~10% of 35B quality for code tasks while loading 10-20x faster.

> **Note:** The `max_loaded_models` change must be in the `lemonade-config` ConfigMap (`defaults.json`), NOT in `/root/.cache/lemonade/config.json` — the server overwrites the runtime config from the ConfigMap on startup.

---

## 3. Contributor Relay — false completion + timer hang

### Problem

The contributor relay (`bin/contributor-relay.sh`) had three bugs:

| Bug | Effect |
|-----|--------|
| Goose network errors (`> Enter to send`) matched as idle → reported `task_complete` falsely | Tasks silently lost, hub reassigned same task forever |
| `setInterval` timer in `startProgressReporting()` stopped firing after certain error states | Pod appeared healthy but never reported progress or completion |
| No task timeout — hung tasks ran forever | Combined with bug 2 = pod bricked until restart |

### Fix

Applied upstream fix [kubestellar/hive#1573](https://github.com/kubestellar/hive/pull/1573) (merged Jun 16):

1. **Network error detection in `checkTmuxIdle()`** — returns `false` (not idle) when `Network error:` / `Could not connect` / `Please resend your message` is detected, then presses Enter to retry
2. **`failCurrentTask()` helper** — consolidates cleanup (clear intervals, clear timeouts, send `task_failed`) into one function, preventing orphaned timers
3. **`MAX_TASK_DURATION_MS` (30 min)** — uses `setTimeout` (async, doesn't block event loop) instead of checking in the polling interval

Deployed via ConfigMap mount over `/usr/local/bin/contributor-relay.sh`:

```yaml
volumes:
  - name: patched-relay
    configMap:
      name: contributor-relay-patched
      defaultMode: 0755
volumeMounts:
  - name: patched-relay
    mountPath: /usr/local/bin/contributor-relay.sh
    subPath: contributor-relay.sh
```

### Justification

The relay is a single-threaded Node.js process. Synchronous `execSync()` calls block the event loop, which can starve `setInterval` timers. The upstream fix uses `setTimeout` (which survives event-loop congestion better) and the `failCurrentTask()` helper ensures cleanup always runs. The network error retry (pressing Enter in tmux) is the correct recovery: goose will retry the API call, and if the backend is healthy, it succeeds. If not, the next idle check retries again.

---

## 4. Contributor Deployment — liveness probe + security

### Problem

The contributor had no liveness probe and violated PodSecurity standards.

### Fixes

**Liveness probe:**
```yaml
livenessProbe:
  exec:
    command:
      - bash
      - -c
      - |
        grep -q contributor-relay /proc/*/cmdline 2>/dev/null &&
        tmux has-session -t contributor 2>/dev/null &&
        [ $(grep -l "^State:.*Z" /proc/*/status 2>/dev/null | wc -l) -lt 50 ]
  initialDelaySeconds: 90
  periodSeconds: 60
  timeoutSeconds: 15
  failureThreshold: 3
```

| Check | Why |
|-------|-----|
| Relay process alive (`contributor-relay` in `/proc/*/cmdline`) | Detects relay crash |
| Tmux session exists | Detects tmux crash |
| Zombie processes < 50 | Detects goose CLI leak (zombies accumulate when goose hangs) |

**Gotcha:** `grep -c "^State:.*Z" /proc/*/status` returns **per-file** counts when glob expands to multiple files, causing `[: too many arguments`. Fixed with `grep -l ... | wc -l` (count files, not per-file matches).

**Security context (PodSecurity restricted):**
```yaml
securityContext:           # pod-level
  runAsUser: 1000
  runAsGroup: 1000
  seccompProfile:
    type: RuntimeDefault
containers[].securityContext:  # container-level
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
```

### Justification

`runAsNonRoot: true` requires the image to have a numeric UID — the container uses `USER dev` (string username), so explicit `runAsUser: 1000` is needed. Dropping all capabilities + RuntimeDefault seccomp follows PodSecurity restricted profile.

---

## 5. Tailscale MagicDNS — pod network bypass

### Problem

After fixing CoreDNS, `lemonade.manatee-basking.ts.net` (Tailscale MagicDNS) stopped resolving from pods. CoreDNS doesn't have a route to Tailscale's `100.100.100.100` DNS.

### Fix

Changed `OPENAI_BASE_URL` from MagicDNS hostname to direct Tailscale IP:

```diff
- OPENAI_BASE_URL: https://lemonade.manatee-basking.ts.net/v1
+ OPENAI_BASE_URL: https://100.73.3.51/v1
```

### Justification

The Lemonade pod uses `hostNetwork: true` and is reachable via its Tailscale IP (`100.73.3.51`) from any pod that can route to Tailscale addresses (which works on this cluster's Flannel setup). MagicDNS requires the Tailscale DNS resolver, which is only available to processes WITH a Tailscale interface. Direct IP is more reliable and avoids DNS dependency.

---

## Deployment Manifest Reference

The contributor deployment ConfigMap and Secret are generated via the upstream Justfile:

```bash
cd kubestellar/hive
just contribute-k8s kubestellar-hive | kubectl apply -f -
```

The Deployment itself is manually managed. Key env vars for our setup:

| Env | Value | Why |
|-----|-------|-----|
| `GOOSE_PROVIDER` | `openai` | Lemonade exposes OpenAI-compatible API |
| `GOOSE_MODEL` | `Qwen3.6-27B-GGUF` | Best balance of speed vs quality on Strix Halo |
| `OPENAI_BASE_URL` | `https://100.73.3.51/v1` | Direct Tailscale IP (bypasses MagicDNS) |
| `OPENAI_API_KEY` | `dummy` | Lemonade doesn't require auth internally |

---

## Upstream Issues

- [#1566](https://github.com/kubestellar/hive/issues/1566) — Contributor relay bugs (filed by us)
- [#1573](https://github.com/kubestellar/hive/pull/1573) — Fix merged (same day!)
