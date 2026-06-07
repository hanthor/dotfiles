# github

**Tags:** `secrets`, `github`
**Secrets needed:** Yes (only on first auth — once `gh` is authenticated, BW is not required)
**Runs on:** All machines with `gh` installed

Logs `gh` in via a BW-stored PAT (only if not already authenticated), then registers this host's SSH key with GitHub for both auth and signing.

## What it does

1. Ensures `github.com`'s ed25519 host key is in `~/.ssh/known_hosts` (prevents MITM warnings on first push).
2. `gh auth status` — if already authenticated, skip the token fetch entirely (no BW dependency for steady-state).
3. If not authenticated and BW is unlocked → `bw get password github-token` → `gh auth login --with-token`. If the BW item is missing, emits a one-line warning and continues.
4. Sets `gh config set git_protocol ssh`.
5. Lists existing keys on the GitHub account. For each key type (auth + signing), runs `gh ssh-key add` if this host's key isn't already there.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `gh auth status` says `not logged in` after apply, vault locked | First run on this host with BW locked | Unlock BW and re-run `just apply-tags github`, or `gh auth login` manually |
| Warning: `No 'github-token' item found` | BW vault doesn't have the PAT | Create a BW *login* item named `github-token` with your PAT as the password |
| Key registration silently fails | `gh ssh-key add` returned non-zero (failed_when:false) — possibly key was just deleted on github.com side | Inspect with `gh ssh-key list` and re-run the role |
| Stale keys clutter github.com | This host's previous key was rotated; the old gh entry stays forever | Delete the old key manually at <https://github.com/settings/keys> — no automated cleanup yet |

## How to verify

```bash
gh auth status                  # Should say "Logged in" with this account
gh ssh-key list | grep "$(hostname)"   # Should show <hostname>-auth and <hostname>-signing
git log --show-signature -1     # Latest commit should show "Good \"git\" signature for ..."
```

## Notes

- Depends on the `ssh_keys` role running first (the key must exist on disk).
- The signing key registration enables the "Verified" badge on commits — only if your local `~/.gitconfig` is also set to sign with the SSH key (the `git` role handles this).
- The PAT in BW needs `admin:public_key`, `write:gpg_key`, and `read:user` scopes for the registrations to succeed.
