# secret-broker (Phase 1 spike)

A tailnet-only secrets broker for [QR secret onboarding (#49)](https://github.com/hanthor/dotfiles/issues/49).
See the design in [`docs/src/qr-onboarding.md`](../../docs/src/qr-onboarding.md).

**Status: spike, compile-verified only.** It builds and vets; it has *not* been
run end-to-end (that needs a `TS_AUTHKEY` to bring the broker onto the tailnet,
which wasn't minted in the session that wrote this). The secret source is a stub
— no real secret material. The point is to prove **identity-gated delivery**.

## What it does

Joins the tailnet as its own node via `tsnet` and serves `GET /v1/secrets` over
the tailnet only (`tsnet.Listen` binds the tailnet interface by construction —
no host port is exposed). For each request it resolves the caller's *verified*
identity with `LocalClient().WhoIs(remoteAddr)` — the WireGuard-authenticated
peer, not anything the caller asserts — and enforces:

1. **Admission gate** — the caller must carry an ACL tag (default `tag:fleet`).
   This is *coarse*: every fleet node has it, so it gates reachability, not which
   secrets you get.
2. **Scoping by `StableNodeID`** — the unforgeable node ID assigned by the
   coordination server. We deliberately **do not** key on hostname/DNSName:
   Phase 0 sets `--hostname=<name>` and that is user-settable, so a malicious
   node could claim to be `bihar`. Hostname is echoed back for display only.
3. **Bootstrap-of-trust, made explicit** — a brand-new node has no prior
   `StableNodeID` mapping. That first-contact case is a labelled decision point
   in `SecretsFor` (`-tofu` trust-on-first-use for the spike). In production this
   is exactly where a **phone-conveyed one-time pairing token** must gate
   issuance — it is not an implicit map lookup.

The response echoes the resolved identity (`stableID`, `hostname`, `tags`) so you
can *see* that authorization is scoped to `stableID` and that hostname is
whatever the node claimed.

## Build

```bash
cd tools/secret-broker
go build .
# Note: tailscale.com pulls a large dep tree (gvisor, wireguard-go). If /tmp is a
# small tmpfs, point Go's scratch at a bigger disk:
#   GOTMPDIR=$HOME/.cache/gotmp go build .
```

## Run (on the intended broker host — e.g. bihar)

```bash
# Mint a tagged, ideally ephemeral auth key in the Tailscale admin for the broker
# node (recommend a dedicated tag, e.g. tag:secret-broker, owned by you).
export TS_AUTHKEY=tskey-auth-...
./secret-broker -tofu            # spike: auto-register unknown nodes
# flags: -hostname (default secret-broker) -addr (:8080) -require-tag (tag:fleet)
#        -state-dir  -tofu
```

## Test (from any fleet node on the tailnet)

```bash
curl -s http://secret-broker:8080/v1/secrets | jq
```

Expected (spike, with `-tofu`): a JSON blob echoing your node's `stableID`, real
`hostname`, `tags`, `provenance: "tofu-first-contact"`, and a
`PLACEHOLDER_BOOTSTRAP_SECRET`. A node lacking `tag:fleet` gets `403`.

**Forgeability demo:** on a second fleet node, `sudo tailscale up
--hostname=bihar` then curl the broker — the response still shows *that node's*
own `stableID` (not bihar's), proving hostname claims don't move authorization.

## Wiring real secrets (next steps, not in the spike)

- Replace `stubSource` with a `bwSource` that, given a `StableNodeID`, resolves
  the node name from your registry and runs least-privilege `bw get …` for only
  the secrets that node needs (kubeconfig / ssh / tailscale authkey) — never a
  full `BW_SESSION` where avoidable.
- Replace `-tofu` with pairing-token verification (Phase 1 proper): the phone
  mints a short-TTL single-use token at approval time; the broker requires it on
  first contact and binds it to the node's `StableNodeID`.
- Add a Tailscale ACL that only lets `tag:fleet` reach the broker's port, so the
  WhoIs tag check is defense-in-depth, not the only layer.
- Phase 2: out-of-band verification fingerprint shown on phone + machine; TTLs.
