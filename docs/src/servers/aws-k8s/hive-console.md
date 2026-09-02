# Hive console

A single page for the whole fleet at **<https://hive.tunaos.org/console>**:
provider headroom, hive agent health, contributor workers, PR/issue flow over
time, and per-agent backend/model/pause/kick controls.

| Where | What |
|---|---|
| `talos-k8s/hive-console/app.py` | the whole app — stdlib only, no dependencies |
| `talos-k8s/hive-console/console.yaml` | Deployment, RBAC, Service, Ingress |
| `talos-k8s/hive-console/deploy.sh` | publishes `app.py` as a ConfigMap + rolls the pod |

## Sign-in

There is no separate login. The console validates the **same `hive_session`
cookie** the hive dashboard issues, by reading hive's own session store off the
PVC. Sign in once at <https://hive.tunaos.org> via GitHub device flow and the
console is authenticated too; the `authorized_users` allowlist keeps working
unchanged.

That only works because it is served as a **path on the same host**. Cookies are
host-scoped and hive sets no `Domain` attribute, so moving the console to its
own hostname (`factory.tunaos.org`, say) would need its own DNS record, its own
certificate and its own login — the shared session would not follow it.

## How it gets its data

| Panel | Source |
|---|---|
| Anthropic headroom | live, from the Claude OAuth token on the hive PVC |
| DeepSeek balance | live, `api.deepseek.com/user/balance` |
| google / openai headroom | `configmap/hive-provider-usage`, published by `hive-rotate.sh` |
| Agents + watchdog conditions | hive `/api/status` via `X-Hive-Internal` |
| Contributor pods | Kubernetes API via its ServiceAccount |
| Activity chart | `configmap/hive-activity-series`, published by `hive-metrics.sh` |

google and openai headroom can only be probed by driving a CLI in a tmux pane,
which a plain HTTP service cannot do — hence the ConfigMap hand-off. The page
shows **how old** those readings are, so a stale number reads as stale rather
than as truth.

## Reads vs writes

- **Reads** use `X-Hive-Internal`, which is read-only at the hive.
- **Writes** forward *your own* owner cookie, so hive re-validates every change
  and it is attributable to you rather than to the console.

## Things that will bite you

**`runAsUser: 1001` is load-bearing.** `dashboard-sessions.json` is mode `0600`
owned by hive's `dev` user (uid 1001). Any other uid gets `EPERM` and *every*
request 401s despite a perfectly valid cookie. The mount is `readOnly`, so that
uid can still only read.

**The PVC mount requires same-namespace, same-node.** An RWO volume binds to one
node (several pods on that node may share it), so the Deployment copies hive's
`nodeSelector` and control-plane toleration. Move either and the pod sits
`Pending`.

**Kicks are dispatched in the background.** A kick blocks until the agent's CLI
answers, which for a busy TUI outlives any sane request timeout — the same
reason `hive-rotate.sh` backgrounds them.

**The POST body is drained before the auth check.** Returning 401 early left the
body in the keep-alive socket, which the server then parsed as the next request
line — producing `Unsupported method ('agent=guide&op=kickPOST')` and a bogus
501 for what was actually a clean 401.

## Updating it

```bash
./talos-k8s/hive-console/deploy.sh
```

`app.py` is a real file in git, published into a ConfigMap and run on stock
`python:3.12-slim`. The Deployment carries a checksum of it, so changing the
code actually rolls the pod instead of leaving the old copy running.

See also: [hive operations control plane](hive-ops.md), [cluster
handbook](cluster.md).
