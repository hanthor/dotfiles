# bitwarden

**Tags:** `secrets`, `bitwarden`  
**Secrets needed:** Yes (provides secrets to other roles)  
**Runs on:** All machines

Resolves a Bitwarden session token for use by all other secrets-tagged roles.

## What It Does

1. Checks for `BW_SESSION` environment variable (forwarded over SSH)
2. Falls back to cached session at `/tmp/bw_session`
3. Falls back to interactive `bw unlock` (prompts for master password)
4. Caches the resolved token to `/tmp/bw_session`
5. Verifies the session is valid with `bw status`

If no session can be resolved, all subsequent `secrets`-tagged roles are skipped with a warning.

## Notes

- This role must run *before* any other secrets role
- The `sshd` role ensures `BW_SESSION` can be forwarded over SSH
- For remote applies, your local session is forwarded — no unlock needed on the target
