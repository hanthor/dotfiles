# secret-broker

Tailnet identity secret broker for [QR secret onboarding (#49)](https://github.com/hanthor/dotfiles/issues/49).
Design: [`docs/src/qr-onboarding.md`](../../docs/src/qr-onboarding.md).

Delivers a new/re-aligned machine its first secrets over the tailnet, authorized
by the machine's **unforgeable tailnet identity** plus an **operator approval**
that mirrors the Tailscale device-approve you already do on your phone. No master
password on the new box; no secret ever travels in a QR.

## Verification status

- `go build` + `go vet` clean; the security-critical gating logic is **unit-tested**
  (`broker_test.go`, deny-paths) and passing.
- **Not run end-to-end.** A live run needs a `TS_AUTHKEY` (to put the broker on
  the tailnet) and a Bitwarden Secrets Manager token — neither minted in the
  session that wrote this. Follow the [runbook](#operator-runbook) to run it.
- The client is a **manual, opt-in** `just` recipe. It is deliberately **not**
  wired into `just apply`/onboarding, so an untested bug here cannot break fleet
  onboarding.

## How authorization works

Every request is resolved to the caller's *verified* identity via
`LocalClient().WhoIs(remoteAddr)` — the WireGuard-authenticated peer, never
anything the caller asserts. Then:

1. **Admission** — the caller must carry an ACL tag (default `tag:fleet`). Coarse:
   every fleet node has it, so it gates reachability, not which secrets you get.
2. **Authorization by `StableNodeID`** — the coordination-server-assigned, un­forgeable
   node id. We never key on hostname: Phase 0 sets `--hostname=<name>` and it is
   user-settable, so a node could claim to be `bihar`. Hostname is display-only.
3. **Race-free pairing** — an unknown eligible node's request is *queued*
   (`202 pending`) with a fingerprint. The operator approves that **specific
   StableID** (`POST /v1/admin/approve?id=…`, admin-gated). We never auto-approve
   "the next node within a window" — `tag:fleet` is broadly held, so a time-only
   window is a race; identity-bound approval is not.
4. **Least privilege** — an authorized node receives only the secrets its policy
   lists (plus shared defaults), fetched from Bitwarden Secrets Manager.

## Endpoints

| Method | Path | Who | Purpose |
|--------|------|-----|---------|
| GET | `/v1/secrets` | any `tag:fleet` node | request secrets; `200` if approved, `202` if pending, `403` if untagged |
| GET | `/v1/admin/pending` | admin StableID | list queued requests (stableID, hostname, fingerprint) |
| POST | `/v1/admin/approve?id=<stableID>` | admin StableID | approve a specific node |
| GET | `/healthz` | any | liveness |

## Secret source & blast radius

`-source=bws` reads from **Bitwarden Secrets Manager** via the `bws` CLI,
authenticated by a machine-account token in `BWS_ACCESS_TOKEN` — **read-scoped to
a single onboarding project, no vault master password**. That is a categorically
smaller target than the fleet's normal `bw unlock` + master-password path.

**Still:** the broker holds unattended read access to every secret it can serve,
so **compromising the broker host = compromising those secrets**. Least-privilege
per client shrinks each *client's* exposure, not the *broker's*. Run it on a
trusted, minimal, always-on host, keep the token read-scoped to the onboarding
project only, and treat the host as sensitive. `-source=stub` returns placeholders
for local testing.

### Where to run it

**Not on bihar** — bihar is a Talos node: immutable, API-only, no SSH/systemd, so
it can't host a systemd binary. Two viable homes:

- **A non-Talos always-on host (recommended): a VPS like `telengana` or `matrix`.**
  Runs the systemd unit directly, and — importantly — stays available to onboard
  machines **even when the home Talos cluster is down** (it was offline as of this
  writing). A bootstrap-of-trust broker should not depend on the thing you're
  often bootstrapping access *to*.
- **In-cluster (Talos-native), when the cluster is up:** deploy as a Kubernetes
  Deployment with `TS_AUTHKEY`/`BWS_ACCESS_TOKEN` as k8s Secrets — see
  `deploy/secret-broker.k8s.yaml` and `Dockerfile`. Consolidated, but coupled to
  cluster uptime.

## Build

```bash
cd tools/secret-broker
go build .
# tailscale.com pulls a big dep tree (gvisor, wireguard-go). If /tmp is a small
# tmpfs, point Go's scratch at a bigger disk:  GOTMPDIR=$HOME/.cache/gotmp go build .
go test ./...    # runs the deny-path gating tests
```

## Client recipes (manual, opt-in)

From the repo root (`BROKER_URL` overrides the default `http://secret-broker:8080`):

```bash
# On the NEW node — request secrets (prints your fingerprint + status):
just broker-request

# On your ADMIN node (a StableID in the broker's -admins list) — see & approve:
just broker-pending
just broker-approve <stableID>     # verify the fingerprint matches first

# Print this node's own StableID (to compare against the pending list):
just broker-myid
```

## Operator runbook

Live steps that must be done by hand (they can't be run from an automated
session — they mint credentials and touch your Tailscale/BW tenancy):

1. **Broker's own tailnet node.** In the Tailscale admin, mint an auth key
   (ideally ephemeral) tagged for the broker, e.g. `tag:secret-broker`. Add ACL
   `tagOwners` for it. Export as `TS_AUTHKEY` on the broker host.
2. **Read-scoped secrets store.** In Bitwarden Secrets Manager: create a project
   (e.g. `fleet-onboarding`), add the onboarding secrets to it, create a **machine
   account** with **read** access to *only* that project, and generate its access
   token. Export as `BWS_ACCESS_TOKEN`. Install `bws`.
3. **Admin identity.** Get your admin machine's StableID (`just broker-myid` on it)
   and pass it as `-admins` (comma-separated for more than one).
4. **Policy.** Copy `policy.example.json` → `policy.json` and map each node's
   StableID → the SM secret ids it may receive (`just broker-myid` on a node
   prints its StableID). Keep it least-privilege. The file names *which* secrets a
   node may get — no secret material — so it is safe to commit. Parsing is strict
   (unknown fields rejected), and the shipped example is covered by a test.
5. **Run** on a non-Talos always-on host (VPS) via the systemd unit
   `deploy/secret-broker.service.example`, or in-cluster via
   `deploy/secret-broker.k8s.yaml` (see [Where to run it](#where-to-run-it)):
   ```bash
   TS_AUTHKEY=… BWS_ACCESS_TOKEN=… \
     ./secret-broker -source=bws -admins=<your-stableID> -config=policy.json
   ```
6. **ACL defense-in-depth** (optional but recommended): restrict who can reach the
   broker port so the WhoIs tag check is the second layer:
   ```jsonc
   // tailnet ACL
   {"action":"accept","src":["tag:fleet"],"dst":["tag:secret-broker:8080"]}
   ```
7. **First enrollment.** On the new node: `just broker-request` → note the
   fingerprint + `202 pending`. On your admin node: `just broker-pending`, confirm
   the fingerprint matches, `just broker-approve <stableID>`. Re-run
   `just broker-request` on the node → `200` with its secrets.

## Not done here (deliberately)

Live provisioning, the real per-node policy values, deploy automation, and ACL
changes are runbook steps, not executed code — they can't be verified from this
environment. Wiring the client into `just onboard`/`apply` waits until the flow
has been run live at least once.
