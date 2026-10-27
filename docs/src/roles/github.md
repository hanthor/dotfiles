# github

**Unit:** `github` (`units/github.sh`; see [Units](../units.md))  
**Tags:** `secrets`, `github`  
**Secrets needed:** Only on first auth; once `gh` is authenticated Bitwarden is not used  
**Runs on:** All machines with `gh` installed (`SKIPPED:` otherwise)

Logs `gh` in via a Bitwarden-stored PAT (only if not already authenticated), then registers this host's SSH key with GitHub for both authentication and signing. With `--no-secrets`, only the local known-hosts step runs; the unit does not invoke `gh` or Bitwarden.

## Steps

1. `github known_hosts`: ensure github.com's ed25519 host key is in `~/.ssh/known_hosts`.
2. `gh login`: skipped when `gh auth status` succeeds. Otherwise, with an unlocked vault, `bw get password github-token` → `gh auth login --with-token`. Locked vault or missing item prints a `PARTIAL:` line.
3. `register SSH keys`: needs a token with `admin:public_key` and `admin:ssh_signing_key` (otherwise a `PARTIAL:` line with the regenerate-PAT link). For each of authentication and signing, `gh ssh-key add ~/.ssh/id_ed25519.pub --title <machine>-auth|-signing` unless `gh ssh-key list` already shows the key with that type. If the list fails, the unit fails without registering either key.

GitHub CLI configuration, including `git_protocol: ssh`, is managed by chezmoi, not this unit.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `PARTIAL: gh not logged in; vault locked` | First run on this host with Bitwarden locked | `bw unlock`, then `just apply-tags github`, or `gh auth login` |
| `PARTIAL: no 'github-token' item` | Vault has no PAT | Create a login item `github-token` with the PAT as the password |
| `PARTIAL: GitHub token lacks admin:public_key / admin:ssh_signing_key` | PAT scopes | Regenerate the PAT with those scopes and update the item |
| `warn: failed to list GitHub SSH keys; registration skipped` | `gh ssh-key list` failed | Check GitHub access and re-run; no keys were added |
| `warn: failed to upload SSH ... key` | `gh ssh-key add` failed | Inspect with `gh ssh-key list` and re-run |

## Verify

```bash
gh auth status
gh ssh-key list | grep "$(cat /etc/dotfiles-machine)"   # <machine>-auth and <machine>-signing
```

## Notes

- Needs `~/.ssh/id_ed25519.pub`, written by the `ssh_keys` role; the units run after the playbook, so a first apply gets both in one pass.
- The "Verified" badge also needs the signing config in `~/.gitconfig` (the chezmoi-managed [git](git.md) config).
- Stale keys from rotated machine keys are not cleaned up: delete them at <https://github.com/settings/keys>.
