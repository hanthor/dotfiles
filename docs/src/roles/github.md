# github

**Unit:** `github` (`units/github.sh`; see [Units](../units.md))  
**Tags:** `secrets`, `github`  
**Secrets needed:** Only on first auth; once `gh` is authenticated Bitwarden is not used  
**Runs on:** All machines with `gh` installed (`SKIPPED:` otherwise)

Logs `gh` in via a Bitwarden-stored PAT (only if not already authenticated), then registers this host's SSH key with GitHub for both authentication and signing. With `--no-secrets`, only the local known-hosts step runs; the unit does not invoke `gh` or Bitwarden.

## Steps

1. `github known_hosts`: ensure github.com's pinned ed25519 host key is in `~/.ssh/known_hosts`, including when the existing entry is hashed. A conflicting ed25519 key, a revoked pinned key, or a symlinked known-hosts file fails closed without changing the file; inspect and resolve it before retrying.
2. `gh login`: skipped when `gh auth status` succeeds. Otherwise, with an unlocked vault, `bw get password github-token` → `gh auth login --with-token`. Locked vault or missing item prints a `PARTIAL:` line.
3. `register SSH keys`: needs a token with `admin:public_key` and `admin:ssh_signing_key` (otherwise a `PARTIAL:` line with the regenerate-PAT link). Authentication and signing keys are listed separately using GitHub's API, so an account with no keys is supported. Each missing type is added with `gh ssh-key add ~/.ssh/id_ed25519.pub --title <machine>-auth|-signing`. A list or upload failure does not prevent attempting the other type, and the unit reports failure.

GitHub CLI configuration, including `git_protocol: ssh`, is managed by chezmoi, not this unit.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `PARTIAL: gh not logged in; vault locked` | First run on this host with Bitwarden locked | `bw unlock`, then `just apply-tags github`, or `gh auth login` |
| `PARTIAL: no 'github-token' item` | Vault has no PAT | Create a login item `github-token` with the PAT as the password |
| `PARTIAL: GitHub token lacks admin:public_key / admin:ssh_signing_key` | PAT scopes | Regenerate the PAT with those scopes and update the item |
| `warn: failed to list GitHub SSH ... keys; registration skipped` | GitHub API lookup failed | Check GitHub access and re-run; the unverified key type was not added |
| `FAIL  conflicting GitHub ed25519 host key` | Existing host key differs from the pinned key | Verify GitHub's published host-key fingerprints and inspect the existing entry before removing or replacing it |
| `warn: failed to upload SSH ... key` | `gh ssh-key add` failed | Inspect with `gh ssh-key list` and re-run |

## Verify

```bash
gh auth status
gh ssh-key list | grep "$(cat /etc/dotfiles-machine)"   # <machine>-auth and <machine>-signing
```

## Notes

- Needs `~/.ssh/id_ed25519.pub`, written by the SSH keys unit; the runner orders SSH keys before GitHub and serializes GitHub and SSH mesh known-hosts updates.
- The "Verified" badge also needs the signing config in `~/.gitconfig` (the chezmoi-managed [git](git.md) config).
- Stale keys from rotated machine keys are not cleaned up: delete them at <https://github.com/settings/keys>.
