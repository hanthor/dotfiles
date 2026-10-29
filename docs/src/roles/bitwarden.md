# bitwarden

**Tags:** `secrets`, `bitwarden`
**Secrets needed:** Yes (provides secrets to other roles)
**Runs on:** All machines

Resolves a Bitwarden session, refreshes the local vault cache, and publishes a single `secrets_available` host fact that every other BW-using role consumes. Failure to unlock is **never fatal** to the play; it's reported once at the end and downstream BW operations are skipped cleanly.

## What it does

1. Resolves `BW_SESSION` in this order: environment → `/tmp/bw_session` cache → interactive `bw unlock`.
2. Runs `bw sync` with a hard 15 s timeout (so a flaky vault server can't hang the whole play).
3. Calls `bw status` and sets `secrets_available` (boolean host fact) — `true` only if `bw` is installed, a session was resolved, and the vault actually reports `unlocked`.
4. If a session is set but the vault is still locked, emits a one-line debug warning so the operator knows secrets work is being skipped here. On a remote apply, this means target-side session resolution did not unlock the target vault.

Every BW-using role downstream gates on `when: secrets_available | default(false)`. The end-of-play `post_tasks` summary then prints one of three messages:

| State | Message |
|---|---|
| unlocked | `vault unlocked — all secret roles executed normally` |
| locked   | `Bitwarden vault was LOCKED — … skipped. To enable: bw unlock …` |
| `--skip-tags secrets` | `SKIPPED (--skip-tags secrets). Run dots-apply to include …` |

## Remote applies

`just apply-remote <host>` (and `just apply-remote-tags <host> <tags>`) resolve
the Bitwarden session on the **target host**; they do not forward the local
host's `BW_SESSION`:

1. `scripts/bw-resolve.sh remote <host>` unlocks Bitwarden on the target and
   prints that host's session token. If the remote CLI is logged out, it tries
   the configured API-key and master-password paths, then falls back to an
   interactive unlock over `ssh -t`.
2. The recipe exports the returned `BW_SESSION` inline in the remote command
   and caches it in the target's `/tmp/bw_session`.
3. The remote `bitwarden` role runs `bw status`; when it reports `unlocked`,
   `secrets_available` becomes true and secrets work proceeds.

A session token is valid only on the host that unlocked it. If target-side
resolution fails, the remote vault remains locked and BW-using tasks skip
cleanly. See the [full remote apply flow](../bitwarden.md#remote-apply).

## How to verify it ran correctly

- `just doctor` will show `vault unlocked` if BW is good on this host.
- Check the end-of-play summary line printed by every `just apply*`.
- Look for any task in `ansible-playbook` output with a `[bitwarden : …]` prefix that ended in `failed:` — should never happen; only "skipping" is acceptable.

## Notes

- Must run before any other secrets role (it does, by position in `site.yml`).
- The cached `/tmp/bw_session` persists for the user across reboots only as long as `/tmp` survives (most modern systemd boots clear it). The role re-resolves the session on every play.
- `bw sync` failure is non-fatal; downstream operations use the locally cached vault, which may be stale.
