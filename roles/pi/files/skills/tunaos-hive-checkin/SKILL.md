---
name: tunaos-hive-checkin
description: Check the health of the self-hosted tuna-os Hive at school.tunaos.org (legacy alias hive.tunaos.org; all Hives on hub.tunaos.org) (AWS Talos cluster) — whether the governor and agents are actually producing PRs/issues, whether config changes really took effect, and where its known landmines are. Use when asked to "check on the hive", "is the hive working", "is it opening PRs", or when changing agent models/repos/config on hive.tunaos.org.
---

# tuna-os Hive check-in

The tuna-os Hive is a **self-hosted spoke** (`kubestellar/hive` v4) running on
the AWS Talos cluster, served publicly at `https://school.tunaos.org` (legacy alias `hive.tunaos.org`; the hub at `https://hub.tunaos.org` shows every Hive)
(Cloudflare-proxied to the cluster's Traefik ingress).

It runs its own agents; contributor CLIs are a separate thing
(see `tunaos-contributor-fleet`).

All `kubectl` below needs that cluster's kubeconfig:

```bash
export KUBECONFIG=~/.kube/config-aws-migration
```

Image: upstream **v6**, `ghcr.io/hivecommons/hive:v6-latest@sha256:…` on all three
spokes (school `hive`, reef `hive-reef`, hanthor `hive-hanthor`). The version is
owned by the **hive-operator** (`tuna-os/hive-operator`, ns `hive-system`,
`HiveRelease` controller) — never `kubectl set image` by hand: a second writer is
exactly how the fleet was rolled back to v5 every night until 2026-10-01 (the old
`hive-upgrade` CronJob, now suspended). Current version is in the Deployment
annotation `hive.tunaos.org/version`.

Manifests: `~/.local/share/dotfiles/talos-k8s/hive/spokes/<spoke>/manifest.yaml`
(exported from the cluster; secrets out of band). Who owns each job (bash
CronJob vs operator controller): `talos-k8s/hive/README.md`.

```bash
kubectl -n hive get pods
kubectl get hivespokes,hivereleases,modelladders,sharedauths
kubectl -n hive get cronjobs
```

## Fast health sweep

```bash
POD=$(kubectl get pods -n hive -l app.kubernetes.io/name=hive \
      -o jsonpath='{.items[0].metadata.name}')

kubectl -n hive get pods                       # Running? restarts?
kubectl logs -n hive $POD --tail=50            # crash loop? panics?
curl -s -o /dev/null -w '%{http_code}\n' https://school.tunaos.org/api/health   # 200?
# the dashboard / itself returns 401 (login-gated) — that is NORMAL, see below
```

Agent/model state needs the dashboard token (the API is authenticated).
The hive is a **direct-route spoke**: `dashboard.authorized_users` enables
per-user authz, so the Bearer path is DISABLED — use the pod-internal
`X-Hive-Internal` header instead (the only server-to-server credential path):

```bash
TOKEN=$(kubectl get secret -n hive hive-secrets \
        -o jsonpath='{.data.HIVE_DASHBOARD_TOKEN}' | base64 -d)
POD=$(kubectl get pods -n hive -l app.kubernetes.io/name=hive \
      -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n hive $POD -- curl -sS \
  -H "X-Hive-Internal: $TOKEN" http://127.0.0.1:3002/api/status | jq
```

The Node proxy on :3001 strips `X-Hive-Internal` and the Bearer path is dead,
so go through the pod to :3002. Browser access is via GitHub device-flow
sign-in only (`dashboard.authorized_users` allowlists `hanthor`); sessions
persist in `/data/dashboard-sessions.json`.

## Health scale — check these in order

Each rung can be green while the one below it is broken. Work down the list;
don't stop at "pod is Running".

### 1. Pod + API

```bash
kubectl -n hive get pods
curl -s -o /dev/null -w '%{http_code}\n' https://school.tunaos.org/api/health   # 200
curl -s -o /dev/null -w '%{http_code}\n' https://school.tunaos.org/             # 401 = login gate, NORMAL
```

### 2. No agent silently paused

A paused agent is invisible in the happy path but still costs governor cycles.

```bash
POD=$(kubectl get pods -n hive -l app.kubernetes.io/name=hive -o jsonpath='{.items[0].metadata.name}')
TOKEN=$(kubectl get secret -n hive hive-secrets -o jsonpath='{.data.HIVE_DASHBOARD_TOKEN}' | base64 -d)
kubectl exec -n hive $POD -- curl -sS -H "X-Hive-Internal: $TOKEN" \
  http://127.0.0.1:3002/api/status | jq -r '.agents[] | select(.paused) | .name'
```

Empty output is what you want (brainstorm is on-demand and normally paused).

### 3. Rotation is actually running

Rotation/pacing/watchdog run as in-cluster CronJobs in ns `hive` (the himachal
systemd timers were retired 2026-09-24) until the operator takes each one over.
A job promoted to the operator is DELETED, so check both places:

```bash
kubectl -n hive get cronjobs | grep -E 'rotate|watchdog|pace|nudge'
kubectl -n hive logs job/$(kubectl -n hive get jobs --sort-by=.metadata.creationTimestamp -o name | grep hive-rotate- | tail -1 | cut -d/ -f2) | tail -20
kubectl get hivespokes -o custom-columns=NAME:.metadata.name,MODE:.spec.rotationMode,REACHABLE:.status.reachable
kubectl -n hive-system logs deploy/hive-operator --since=30m | tail -20
```

`hive-rotate.sh apply` legitimately takes about two minutes on the loaded node.

### 4. Discord bot (`hive-discord-realtime`)

Posts SSE/bead/GitHub activity into the ops channel. It is REST-based — it does
**not** hold a Discord gateway socket, so "no Discord connection" is normal.
What must be true is an established SSE connection to the hive:

```bash
DPOD=$(kubectl get pods -n hive --no-headers | grep discord | awk '{print $1}')

# a) SSE connection to hive:3002 established?
kubectl exec -n hive $DPOD -- python3 -c "
import socket,struct
for l in open('/proc/net/tcp').read().splitlines()[1:]:
    f=l.split()
    if f[3]=='01':
        ip,port=f[2].split(':')
        print(socket.inet_ntoa(struct.pack('<L',int(ip,16))), int(port,16))"

# b) Discord credentials still valid — the User-Agent is REQUIRED
kubectl exec -n hive $DPOD -- python3 -c "
import os,json,urllib.request
r=urllib.request.urlopen(urllib.request.Request(
  'https://discord.com/api/v10/users/@me',
  headers={'Authorization':'Bot '+os.environ['DISCORD_BOT_TOKEN'],
           'User-Agent':'TunaOS-Hive-Ops/1.0'}),timeout=10)
print(json.load(r)['username'])"

# c) errors recent, or just leftovers from a restart?
kubectl logs -n hive $DPOD --since=15m
```

**Gotcha:** hitting the Discord API without a `User-Agent` returns
**HTTP 403 with Cloudflare `error code: 1010`** — a client-fingerprint block,
*not* a bad token (a bad token gives 401). Always send the UA before concluding
the credentials are dead.

**Silence is the healthy steady state** for this bot: it only logs on errors or
events. Judge it by the established SSE connection, not by log volume. A burst
of `Connection refused` on both `bead poll` and `SSE bridge` that then *stops*
is just the hive pod having restarted underneath it — it reconnects on its own.

### 5. Is it producing? (below)

## The real question: is it *producing*?

"Pod is Running" means nothing. The hive is only working if it opens PRs and
issues. Check authored work, not process state:

```bash
gh search prs --author "hanthor-hive-agent[bot]" --limit 20 \
  --json repository,number,title,createdAt,state
gh search issues --author "hanthor-hive-agent[bot]" --limit 20 \
  --json repository,number,title,createdAt
```

Filter by the **bot**, not by `hanthor` — that's the human account and its PRs
are not the hive's. If the newest item is days old while agents show as
running, the hive is idle-but-alive: check agent panes and the governor's eval
loop in the pod logs.

## Landmines

**Config edits silently revert.** The ACMM policy pack re-asserts default agent
config on every restart unless a field is *operator-owned*. Editing `model:` in
`hive.yaml` looks applied but gets overwritten. Set models through the API,
which marks them operator-owned:

```bash
POD=$(kubectl get pods -n hive -l app.kubernetes.io/name=hive \
      -o jsonpath='{.items[0].metadata.name}')
for a in $(kubectl exec -n hive $POD -- curl -sS \
           -H "X-Hive-Internal: $TOKEN" http://127.0.0.1:3002/api/status | jq -r '.agents[].name'); do
  kubectl exec -n hive $POD -- curl -sS -X PUT \
    -H "X-Hive-Internal: $TOKEN" -H 'Content-Type: application/json' \
    -d '{"backend":"pi","model":"deepseek-v4-flash"}' \
    "http://127.0.0.1:3002/api/config/agent/$a/models"
done
```

Then **restart and re-read `/api/status`** to confirm it stuck. While rotation is
still bash-owned, also add the agent to the rotate CronJob's `HIVE_ROTATE_PIN`,
or rotation moves it again within 20 minutes. Anything else
is assuming.

**The public URL is login-gated, not read-only.** The old
`hive-public-readonly` Traefik middleware (which forced `X-Hive-Role: read`
and 403'd every non-GET) is GONE. Auth is enforced by the dashboard itself:
`DASHBOARD_AUTH_TOKEN` + `dashboard.authorized_users` (direct-route authz).
Unauthenticated requests 401 everywhere; only GitHub device-flow sessions for
allowlisted users (currently just `hanthor`) can read or write. To make
changes programmatically, go through `kubectl exec` to :3002 with
`X-Hive-Internal` (see above). `/api/contribute/*` is exempt, so contributors
still register and reconnect through the public URL.

**Do not re-add the read-only middleware.** It blocked writes for logged-in
users too. If you ever want to harden the public hostname further, the lever
is Traefik-level auth (BasicAuth/forwardAuth), not the read-role middleware.

**Historical v4 notes (image `ghcr.io/hanthor/hive:v4-hotfix`, retired).**
- `HIVE_PROXY_ADVISORY_OK=true` is set because the pod has no NET_ADMIN and
  v4's entrypoint FATALs without the iptables forced-egress (v2 was tolerant).
  Agents still route through the MITM proxy via the HTTPS_PROXY env the Go
  binary sets, so ACMM enforcement applies to explicit-proxy traffic. To get
  full iptables enforcement: drop the env var and grant the container NET_ADMIN.
- The ingresses point at the Go API (`:3002`), not `:3001`. The v4 Node proxy
  refuses to start without `HIVE_DASHBOARD_TOKEN`, and setting it would make
  it inject `X-Hive-Internal` and bypass the direct-route login gate — so it
  stays dead. `:3002` serves the dashboard + API with full authz.
- The dashboard returns **401 with a sign-in page** for unauthenticated
  browsers on both routes (that is the login gate working, not an outage);
  `/api/health` stays public.

**Egress-wedge history (the 7h "dormant" incident).** Agent egress calls
through the MITM proxy used to hang forever (no timeouts anywhere): a stuck
upstream left connections ESTABLISHED with empty queues and agents' sessions
froze on the hung call; the governor kept kicking but every kick's first call
re-hung. Fixed by upstream dial timeouts (#3406) + relay/client-TLS deadlines
(#3456). To detect a recurrence: compare `/proc/net/tcp` connections to
:18443 across ~90s — if the client-side inodes (uid 2001-2010) are identical
and queues are 0:0, connections are wedged; healthy ones recycle. Then check
pod logs for `proxy upstream dial failed` / `TLS handshake failed` timeout
errors — those mean the deadlines are firing (good, fail-fast) vs. old
behavior (silent forever-hang).

**Two different env vars.** `DASHBOARD_AUTH_TOKEN` is the gate the auth
middleware actually reads. `HIVE_DASHBOARD_TOKEN` only feeds an unrelated
Discord integration — setting only that used to leave the dashboard fail-open.
The k8s Secret *key* is `HIVE_DASHBOARD_TOKEN`; the container *env var* must
be `DASHBOARD_AUTH_TOKEN`. Note that since `dashboard.authorized_users` is set,
the authenticate middleware now FAILS CLOSED even with an empty
`DASHBOARD_AUTH_TOKEN` — the allowlist alone forces auth, so don't delete the
token and assume the dashboard reopens; only device-flow sessions work on
this direct-route spoke either way.

**Stale DiskPressure.** kubelet can keep `DiskPressure: True` long after disk
frees, blocking scheduling. If live stats look fine but pods won't schedule:
restarting the node is not a thing on Talos — delete the pod and let it
reschedule (`kubectl delete pod -n hive $POD`).

**Hub listing is blocked upstream, not broken here.** Heartbeats to
`hive.kubestellar.io` return 401 and always will: unauthenticated self-host
registration was deliberately removed (kubestellar/hive#1077) and needs an
operator-issued `HIVE_HUB_SECRET`. Tracked in kubestellar/hive#2847, docs fix
in #2848. Do not "fix" this locally — the 401 is expected.

## Pausing / resuming agents

Routes are `POST /api/pause/{agent}` and `POST /api/resume/{agent}` — **not**
`/api/agents/{agent}/resume`, which returns 405.

On v6, `X-Hive-Internal` with the dashboard token and **no** session cookie is
owner-equivalent (hivecommons/hive#4134), so mutations work headlessly. Verified
2026-10-01 (`{"ok":true,"status":"paused"}`). Do not add a `hive_session` cookie
alongside it — that scopes the request down to that user's role.

```bash
NS=hive
POD=$(kubectl get pods -n $NS -l app.kubernetes.io/name=hive \
      -o jsonpath='{.items[0].metadata.name}')
TOKEN=$(kubectl get secret -n $NS hive-secrets -o jsonpath='{.data.HIVE_DASHBOARD_TOKEN}' | base64 -d)
kubectl exec -n $NS $POD -- curl -sS -X POST \
  -H "X-Hive-Internal: $TOKEN" http://127.0.0.1:3002/api/resume/<agent>
```

(On v5 the header was read-only and every write needed an owner session cookie
`hive_session` scraped from `/data/dashboard-sessions.json`; those expire with
the browser login. That path is gone from the ops scripts and the operator.)

Undeclared pauses are resumed automatically by rotation; to keep an agent paused,
declare it as a hold (rotate CronJob `HIVE_ROTATE_HOLD`, or `HiveSpoke.spec.holds`
once rotation is operator-owned).

Pass the curl straight to `kubectl exec` — wrapping it in `sh -c "…"` with an
interpolated token has produced bogus responses. Confirm against `/api/status`
rather than the response body.

**A paused agent is invisible in the happy path but costs real cycles.** The
governor still computes it as due and then silently skips it. Pause state
persists in `/data/hive-state.json` across restarts with no reason recorded:

```bash
kubectl exec -n $NS $POD -- curl -sS \
  -H "X-Hive-Internal: $TOKEN" http://127.0.0.1:3002/api/status \
  | jq -r '.agents[] | select(.paused) | .name'
```
