# QR Secret Onboarding

> Tracking issue: [hanthor/dotfiles#49](https://github.com/hanthor/dotfiles/issues/49)

Onboard (or re-align) a machine and deliver its secrets **seamlessly and
securely by scanning a QR from your phone** — no master password typed on the new
box, no hand-copied `BW_SESSION`, no chicken-and-egg SSH setup.

## The core problem: bootstrap-of-trust

The hard part is delivering the *first* credential to a machine that has nothing.
Once the box holds any one of {tailnet membership, a single Bitwarden credential},
everything else — the full `BW_SESSION`, kubeconfig, SSH keys, Tailscale auth key
— already flows through existing automation ([`bw-resolve.sh`](https://github.com/hanthor/dotfiles/blob/master/scripts/bw-resolve.sh),
the `tailscale`/`kube`/`ssh_keys` roles). So the whole question is: *how does that
first secret arrive?*

## The spine: Tailscale identity as the bootstrap credential

We already run Tailscale everywhere and Authentik for SSO, so the passwordless +
QR experience is mostly already in the stack:

1. **Approve the new device on your phone.** `tailscale up --qr` renders the login
   URL as a QR; scan it and approve in the Tailscale admin (passwordless via the
   IdP). The box joins the tailnet, tagged `tag:fleet`.
2. **The machine's tailnet identity is then its first credential.** A small
   tailnet-only secrets broker sees the authenticated node identity and hands it
   exactly the secrets it needs, read from Bitwarden server-side.
3. **No secret ever rides in the QR** — the QR carries a login URL; the phone
   approves; the identity does the rest.

Bitwarden stays the source of truth — we're replacing the *bootstrap*, not the
vault. (The `bw` CLI cannot do passwordless "log in with device"; it only supports
password / `--apikey` / `--sso`, so we don't build on that.)

**Bonus:** adopting Tailscale identity here also opens the door to Tailscale SSH
(auth by tailnet identity, ACL-gated), which would have prevented the "kerala
couldn't SSH anywhere" incident — there'd be no `authorized_keys` to fall out of.

## Phases

| Phase | What | Status |
|-------|------|--------|
| **0** | QR tailnet join — `just tailscale-qr` renders the `tailscale up` login URL as a console QR; scan + approve on phone. | **Done** |
| **1** | Identity broker — a tailnet-only service (`tsnet`) that returns a short-TTL `BW_SESSION` (or only the derived secrets) to an authenticated, tagged node. | Planned |
| **2** | Least-privilege + hardening — per-machine secret scoping, TTLs, out-of-band verification fingerprint on phone + machine. | Planned |

### Phase 0 (implemented)

```bash
# On the new machine:
just tailscale-qr <name>
```

Runs interactive `tailscale up --qr --hostname=<name> --advertise-tags=tag:fleet
--accept-routes`. Uses the Tailscale CLI's native `--qr` flag (confirmed on the
fleet's 1.98.x) — no `qrencode` dependency. See the `tailscale-qr` recipe in the
`Justfile`; if `tailscale` isn't installed yet, the recipe installs it first.

## Security requirements (all phases)

- No long-lived secret encoded in a QR that persists on screen/scrollback.
- Tokens are short-TTL and single-use; pairing nonces expire fast.
- Out-of-band verification fingerprint on both phone and machine (anti-MITM).
- Master password stays on the phone; never keyed into the onboarding box.
- Transport is the tailnet (WireGuard) or otherwise E2E-encrypted.
- Repo stays public — code and docs only, never secrets.

## References

- [Onboarding a New Machine](onboarding.md) — practical steps
- [Secrets with Bitwarden](bitwarden.md) — vault structure and the BW handshake
- [`scripts/bw-resolve.sh`](https://github.com/hanthor/dotfiles/blob/master/scripts/bw-resolve.sh) — current session resolution
- Tracking issue [#49](https://github.com/hanthor/dotfiles/issues/49)
