# bitwarden

**Tags:** `secrets`, `bitwarden`
**Secrets needed:** Yes (provides secrets to other roles)
**Runs on:** All machines

Resolves a Bitwarden session, refreshes the local vault cache, and publishes a single `bw_unlocked` host fact that every other BW-using role consumes. Failure to unlock is **never fatal** to the play; it's reported once at the end and downstream BW operations are skipped cleanly.

## What it does

1. Resolves `BW_SESSION` in this order: environment → `/tmp/bw_session` cache → interactive `bw unlock`.
2. Runs `bw sync` with a hard 15 s timeout (so a flaky vault server can't hang the whole play).
3. Calls `bw status` and sets `bw_unlocked` (boolean host fact) — `true` only if `bw` is installed, a session was resolved, and the vault actually reports `unlocked`.
4. If a session is set but the vault is still locked (common on remote applies — see below), emits a one-line debug warning so the operator knows secrets work is being skipped here.

Every BW-using role downstream gates on `when: bw_unlocked | default(false)`. The end-of-play `post_tasks` summary then prints one of three messages:

| State | Message |
|---|---|
| unlocked | `vault unlocked — all secret roles executed normally` |
| locked   | `Bitwarden vault was LOCKED — … skipped. To enable: bw unlock …` |
| `--skip-tags secrets` | `SKIPPED (--skip-tags secrets). Run dots-apply to include …` |

## Why a forwarded BW_SESSION can fail on a remote host

`just apply-remote <host>` forwards your local `BW_SESSION` over SSH. The token is, however, **derived from the master password + the local vault's KDF parameters**. If the remote host's vault has different KDF iterations or a stale cached vault, `bw status` on the remote will keep reporting `locked` despite the forwarded token. This isn't a bug — it's a Bitwarden CLI portability limit. The role detects it via the `bw_unlocked` check and degrades gracefully.

To enable secrets on a remote host where the forwarded session doesn't unlock:

```bash
ssh <host>
bw unlock --raw | tee /tmp/bw_session > /dev/null
chmod 600 /tmp/bw_session
exit
just apply-remote-tags <host> secrets
```

## How to verify it ran correctly

- `just doctor` will show `vault unlocked` if BW is good on this host.
- Check the end-of-play summary line printed by every `just apply*`.
- Look for any task in `ansible-playbook` output with a `[bitwarden : …]` prefix that ended in `failed:` — should never happen; only "skipping" is acceptable.

## Notes

- Must run before any other secrets role (it does, by position in `site.yml`).
- The cached `/tmp/bw_session` persists for the user across reboots only as long as `/tmp` survives (most modern systemd boots clear it). The role re-resolves the session on every play.
- `bw sync` failure is non-fatal; downstream operations use the locally cached vault, which may be stale.
